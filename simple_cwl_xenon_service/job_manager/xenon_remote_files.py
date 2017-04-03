import jpype
import json
import re
import types
import xenon

from xenon.files import OpenOption
from xenon.files import RelativePath

from .job_state import JobState
from .cwl import get_files_from_binding

class XenonRemoteFiles:
    def __init__(self, job_store, x, xenon_config={}):
        """Create a XenonRemoteFiles object.
        Sets up remote directory structure as well, but refuses to
        create the top-level directory.

        Args:
            x: The Xenon object to use.
            xenon_config: A dict containing key-value pairs with Xenon
                configuration.
        """
        self._job_store = job_store
        """The JobStore instance to use."""
        self._x = x
        """The Xenon instance to use."""
        self._fs = self._x.files().newFileSystem(
                xenon_config['files'].get('scheme', 'local'),
                xenon_config['files'].get('location'),
                xenon_config['files'].get('credential'),
                xenon_config['files'].get('properties')
                )
        """The Xenon remote file system to stage to."""
        self._basedir = xenon_config['files']['path']
        """The remote path to the base directory where we store our stuff."""

        # Check that basedir exists, don't create it
        basedir_rel_path = RelativePath(self._basedir)
        basedir_full_path = self._x.files().newPath(self._fs, basedir_rel_path)
        if not self._x.files().exists(basedir_full_path):
            raise RuntimeError(('Configuration error: Base directory {} ' +
                'not found on remote file system').format(basedir_full_path))

        # Create a subdirectory for jobs
        jobsdir_rel_path = RelativePath(self._basedir + '/jobs')
        jobsdir_full_path = self._x.files().newPath(self._fs, jobsdir_rel_path)
        try:
            self._x.files().createDirectories(jobsdir_full_path)
        except jpype.JException(xenon.nl.esciencecenter.xenon.files.PathAlreadyExistsException):
            pass

    def stage_job(self, job_id):
        """Stage a job. Copies any necessary files to
        the remote resource.

        Args:
            job_id The id of the job to stage
        """
        job = self._job_store.get_job(job_id)

        # create work dir
        self._make_remote_dir(job_id, '')
        self._make_remote_dir(job_id, 'work')
        job.workdir_path = self._abs_path(job_id, 'work')

        # stage name of the job
        self._write_remote_file(job_id, 'name.txt', job.name.encode('utf-8'))

        # stage workflow
        self._write_remote_file(job_id, 'workflow.cwl', job.workflow_content)
        job.workflow_path = self._abs_path(job_id, 'workflow.cwl')

        # stage input files
        inputs = json.loads(job.input)
        count = 1
        for name, location, content in job.input_files:
            staged_name = self._create_input_filename(str(count).zfill(2), location)
            count += 1
            self._write_remote_file(job_id, 'work/' + staged_name, content)
            inputs[name]['location'] = self._abs_path(job_id, 'work/' + staged_name)

        # stage input description
        input_json = json.dumps(inputs).encode('utf-8')
        self._write_remote_file(job_id, 'input.json', input_json)
        job.input_path = self._abs_path(job_id, 'input.json')

        # configure output
        job.stdout_path = self._abs_path(job_id, 'stdout.txt')
        job.stderr_path = self._abs_path(job_id, 'stderr.txt')

    def destage_job_output(self, job_id):
        """Download results of the given job from the compute resource.

        Args:
            job_id: The id of the job to download results of.

        Returns:
            A dictionary with output names as keys, and file contents
            as values.
        """
        job = self._job_store.get_job(job_id)
        outputs = json.loads(job.output)
        output_files = []
        for output_name, path in get_files_from_binding(outputs):
            print('Destage path = ' + path + ' for output ' + output_name)
            prefix = 'file://' + self._basedir + '/jobs/' + job_id + '/work/'
            if not path.startswith(prefix):
                raise Exception("Unexpected output location in cwl-runner output: " + path)
            rel_path = path[len(prefix):]
            content = self._read_remote_file(job_id, 'work/' + rel_path)
            output_files.append((output_name, rel_path, content))

        return output_files

    def delete_job(self, job_id):
        """Remove the work directory for a job.
        This will remove the directory and everything in it.

        Args:
            job_id: The id of the job whose work directory to delete.
        """
        self._rm_remote_dir(job_id, '')

    def update_job(self, job_id):
        """Get status from Xenon and update store.

        Args:
            job_id: ID of the job to get the status of.
        """
        job = self._job_store.get_job(job_id)

        # get output
        output = self._read_remote_file(job_id, 'stdout.txt')
        if len(output) > 0:
            job.output = output.decode()

        if job.state == JobState.SUCCESS and job.output_files is None:
            job.output_files = self.destage_job_output(job_id)

        # get log
        log = self._read_remote_file(job_id, 'stderr.txt')
        if len(log) > 0:
            job.log = log.decode()

    def update_all_jobs(self):
        """Get status from Xenon and update store, for all jobs.
        """
        for job in self._job_store.list_jobs():
            self.update_job(job.id)

    def _create_input_filename(self, unique_prefix, orig_path):
        """Return a string containing a remote filename that
        resembles the original path this file was submitted with.

        Args:
            unique_prefix: A unique prefix, used to avoid collisions
            orig_path: A string we will try to resemble to aid
            debugging
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


    def _make_remote_dir(self, job_id, rel_path):
        xenonpath = self._x_abs_path(job_id, rel_path)
        self._x.files().createDirectories(xenonpath)

    def _rm_remote_dir(self, job_id, rel_path):
        x_remote_path = self._x_abs_path(job_id, rel_path)
        self._x_recursive_delete(x_remote_path)

    def _x_recursive_delete(self, x_remote_path):
        x_dir = self._x.files().newAttributesDirectoryStream(x_remote_path)
        x_dir_it = x_dir.iterator()
        while x_dir_it.hasNext():
            x_path_attr = x_dir_it.next()
            if x_path_attr.attributes().isDirectory():
                self._x_recursive_delete(x_path_attr.path())
            else:
                self._x.files().delete(x_path_attr.path())
        self._x.files().delete(x_remote_path)

    def _write_remote_file(self, job_id, rel_path, data):
        """Write a file on the remote resource containing the given raw data.

        Args:
            job_id: The id of the job to write data for
            rel_path: A string with a path relative to the job's directory
            data: A bytes-object containing the data to write
        """
        x_remote_path = self._x_abs_path(job_id, rel_path)
        stream = self._x.files().newOutputStream(x_remote_path, [OpenOption.CREATE, OpenOption.TRUNCATE])
        stream.write(data)
        stream.close()

    def _read_remote_file(self, job_id, rel_path):
        """Read data from a remote file.

        Args:
            job_id: A job from whose work dir a file is read
            rel_path: A string with a path relative to the job's directory
        """
        result = bytearray()

        x_remote_path = self._x_abs_path(job_id, rel_path)
        if self._x.files().exists(x_remote_path):
            stream = self._x.files().newInputStream(x_remote_path)
            buf = jpype.JArray(jpype.JByte)(1024)
            bytes_read = stream.read(buf)
            while bytes_read != -1:
                result = bytearray().join([result, bytearray(buf[0:bytes_read])])
                bytes_read = stream.read(buf)

        return result

    def _abs_path(self, job_id, rel_path):
        """Return an absolute remote path given a job-relative path.

        Args:
            job_id: A job from whose dir a file is read
            rel_path: A string with a path relative to the job's directory
        """
        return self._basedir + '/jobs/' + job_id + '/' + rel_path

    def _x_abs_path(self, job_id, rel_path):
        """Return a Xenon Path object containing an absolute path
        corresponding to the given relative path.

        Args:
            job_id: A job from whose dir a file is read
            rel_path: A string with a path relative to the job's directory
        """
        abs_path = self._abs_path(job_id, rel_path)
        xenon_path = xenon.files.RelativePath(abs_path)
        return self._x.files().newPath(self._fs, xenon_path)
