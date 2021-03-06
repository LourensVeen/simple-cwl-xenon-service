import json
import logging
import re
from typing import Any, Dict, List, cast

import cerulean
from cerulean import Path

from cerise.back_end.cwl import get_files_from_binding
from cerise.back_end.file import File
from cerise.config import Config
from cerise.job_store.sqlite_job_store import SQLiteJobStore


class RemoteJobFiles:
    """Manages a remote directory structure.
    Expects to be given a remote dir to work within. Inside this
    directory, it makes a jobs/ directory, and inside that there
    is a directory for every job.

    Within each job directory are the following files:

    - jobs/<job_id>/name.txt contains the user-given name of the job
    - jobs/<job_id>/workflow.cwl contains the workflow to run
    - jobs/<job_id>/work/ contains input and output files, and is the
      working directory for the job.
    - jobs/<job_id>/stdout.txt is the standard output of the CWL runner
    - jobs/<job_id>/stderr.txt is the standard error of the CWL runner
    """

    def __init__(self, job_store: SQLiteJobStore, config: Config) -> None:
        """Create a RemoteJobFiles object.
        Sets up remote directory structure as well, but refuses to
        create the top-level directory.

        Args:
            job_store: The job store to use.
            config: The configuration.
        """
        self._logger = logging.getLogger(__name__)
        """Logger: The logger for this class."""
        self._job_store = job_store
        """JobStore: The job store to use."""
        self._username = config.get_username('files')
        """str: The remote user name to use, if any."""
        self._basedir = config.get_basedir()
        """Path: The remote path to the directory where the API files are."""

        # Create directories if they don't exist
        self._logger.debug('basedir: {}'.format(self._basedir))
        self._basedir.mkdir(0o750, parents=True, exists_ok=True)
        (self._basedir / 'jobs').mkdir(parents=True, exists_ok=True)

    def stage_job(self, job_id: str, input_files: List[File],
                  workflow_content: bytes) -> None:
        """Stage a job. Copies any necessary files to
        the remote resource.

        Args:
            job_id: The id of the job to stage
            input_files: A list of input files to stage.
            workflow_content: Translated contents of the workflow to be
                    run.
        """
        self._logger.debug('Staging job ' + job_id)
        with self._job_store:
            job = self._job_store.get_job(job_id)

            # create work dir
            self._abs_path(job_id, '').mkdir(
                0o700, parents=True, exists_ok=True)
            self._abs_path(job_id, 'work').mkdir(
                0o700, parents=True, exists_ok=True)
            job.remote_workdir_path = str(self._abs_path(job_id, 'work'))

            # stage name of the job
            self._add_file_to_job(job_id, 'name.txt', job.name.encode('utf-8'))

            # stage workflow
            self._add_file_to_job(job_id, 'workflow.cwl', workflow_content)
            job.remote_workflow_path = str(
                self._abs_path(job_id, 'workflow.cwl'))

            # stage input files
            inputs = json.loads(job.local_input)
            count = 1
            for input_file in input_files:
                if input_file.index is not None:
                    input_desc = inputs[input_file.name][input_file.index]
                else:
                    input_desc = inputs[input_file.name]
                count = self._stage_input_file(count, job_id, input_file,
                                               input_desc)

            # stage input description
            inputs_json = json.dumps(inputs).encode('utf-8')
            self._add_file_to_job(job_id, 'input.json', inputs_json)
            job.remote_input_path = str(self._abs_path(job_id, 'input.json'))

            # configure output
            job.remote_stdout_path = str(self._abs_path(job_id, 'stdout.txt'))
            job.remote_stderr_path = str(self._abs_path(job_id, 'stderr.txt'))
            job.remote_system_out_path = str(self._abs_path(job_id,
                                                            'sysout.txt'))
            job.remote_system_err_path = str(self._abs_path(job_id,
                                                            'syserr.txt'))

    def destage_job_output(self, job_id: str) -> List[File]:
        """Download results of the given job from the compute resource.

        Args:
            job_id: The id of the job to download results of.

        Returns:
            A list of (name, path, content) tuples.
        """
        self._logger.debug('Destaging job ' + job_id)
        output_files = []
        with self._job_store:
            job = self._job_store.get_job(job_id)
            work_dir = self._basedir / 'jobs' / job_id / 'work'
            self._logger.debug("Remote output: {}".format(job.remote_output))
            if job.remote_output != '':
                outputs = json.loads(job.remote_output)
                for output_file in get_files_from_binding(outputs):
                    self._logger.debug(
                        'Destage path = {} for output {}'.format(
                            output_file.location, output_file.name))
                    prefix = 'file://' + str(work_dir) + '/'
                    if not output_file.location.startswith(prefix):
                        raise Exception(
                            'Unexpected output location in cwl-runner output:'
                            ' {}, expected it to start with: {}'
                            .format(output_file.location, prefix))
                    output_file.location = output_file.location[len(prefix):]
                    output_file.source = work_dir / output_file.location
                    output_files.append(output_file)
            else:
                self._logger.error(
                    'CWL runner did not produce any output for job {}!'.format(
                        job_id))

        # output name and location are (immutable) str's, while source
        # does not come from the store, so we're not leaking here
        return output_files

    def delete_job(self, job_id: str) -> None:
        """Remove the work directory for a job.
        This will remove the directory and everything in it, if it exists.

        Args:
            job_id: The id of the job whose work directory to delete.
        """
        job_dir = self._abs_path(job_id, '')
        if job_dir.exists():
            job_dir.rmdir(recursive=True)

    def update_job(self, job_id: str) -> None:
        """Get status from remote resource and update store.

        Args:
            job_id: ID of the job to get the status of.
        """
        self._logger.debug("Updating " + job_id + " from remote files")
        with self._job_store:
            job = self._job_store.get_job(job_id)

            # get output
            output = self._read_remote_file(job_id, 'stdout.txt')
            if len(output) > 0:
                self._logger.debug("Output:")
                self._logger.debug(output)
                job.remote_output = output.decode()

            # get log
            log = self._read_remote_file(job_id, 'stderr.txt')
            if len(log) > 0:
                lines = log.decode().splitlines()
                last_lines = job.remote_error.splitlines()
                first_new_line = len(last_lines)
                job.debug(lines[first_new_line:])
                job.remote_error = log.decode()

    def _stage_input_file(self, count: int, job_id: str, input_file: File,
                          input_desc: Dict[str, Any]) -> int:
        """Stage an input file. Copies the file to the remote resource.

        Uses count to create unique file names, returns the new count \
        (i.e. the next available number).

        Args:
            count: The next available unique count
            job_id: The job id to stage for
            input_file: The input file to stage
            input_desc: The input description whose location \
                    (and secondaryFiles) to update.

        Returns:
            The updated count
        """
        staged_name = _create_input_filename(
            str(count).zfill(2), input_file.location)
        count += 1

        with self._job_store:
            job = self._job_store.get_job(job_id)
            job.info('Staging input file {}'.format(input_file.location))

        target_path = self._abs_path(job_id, 'work/{}'.format(staged_name))
        cerulean.copy(cast(Path, input_file.source), target_path)

        input_desc['location'] = str(
            self._abs_path(job_id, 'work/' + staged_name))

        for i, secondary_file in enumerate(input_file.secondary_files):
            sec_input_desc = input_desc['secondaryFiles'][i]
            count = self._stage_input_file(count, job_id, secondary_file,
                                           sec_input_desc)

        return count

    def _add_file_to_job(self, job_id: str, rel_path: str,
                         data: bytes) -> None:
        """Write a file on the remote resource containing the given raw data.

        Args:
            job_id: The id of the job to write data for
            rel_path: A path relative to the job's directory
            data: The data to write
        """
        remote_path = self._abs_path(job_id, rel_path)
        remote_path.write_bytes(data)

    def _read_remote_file(self, job_id: str, rel_path: str) -> bytes:
        """Read data from a remote file.

        Silently returns an empty result if the file does not exist.

        Args:
            job_id: A job from whose work dir a file is read
            rel_path: A path relative to the job's directory
        """
        try:
            return self._abs_path(job_id, rel_path).read_bytes()
        except FileNotFoundError:
            return bytes()

    def _abs_path(self, job_id: str, rel_path: str) -> Path:
        """Return an absolute remote path given a job-relative path.

        Args:
            job_id: A job from whose dir a file is read
            rel_path: A a path relative to the job's directory
        """
        ret = self._basedir / 'jobs' / job_id
        if rel_path != '':
            ret /= rel_path
        return ret


def _create_input_filename(unique_prefix: str, orig_path: str) -> str:
    """Return a string containing a remote filename that
    resembles the original path this file was submitted with.

    Args:
        unique_prefix: A unique prefix, used to avoid collisions.
        orig_path: A string we will try to resemble to aid
            debugging.
    """
    result = orig_path

    result.replace('/', '_')
    result.replace('?', '_')
    result.replace('&', '_')
    result.replace('=', '_')

    regex = re.compile('[^a-zA-Z0-9_.-]+')
    result = regex.sub('_', result)

    if len(result) > 39:
        result = result[:18] + '___' + result[-18:]

    return unique_prefix + '_' + result
