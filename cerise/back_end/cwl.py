import yaml
from cerise.job_store.job_state import JobState
from .input_file import InputFile

def is_workflow(workflow_content):
    """Takes CWL file contents and checks whether it is a CWL Workflow
    (and not an ExpressionTool or CommandLineTool).

    Args:
        workflow_content (bytes): a dict structure parsed from a CWL
                file.

    Returns:
        bool: True iff the top-level Process in this CWL file is an
                instance of Workflow.
    """
    workflow = yaml.safe_load(workflow_content)
    process_class = workflow.get('class')
    return process_class == 'Workflow'


def get_required_num_cores(workflow_content):
    """Takes a CWL file contents and extracts number of cores required.

    Args:
        workflow_content (bytes): The contents of a CWL file.

    Returns:
        int: The number of cores required, or 0 if not specified.
    """
    workflow = yaml.safe_load(workflow_content)
    hints = workflow.get('hints')
    if hints is None:
        return 0

    resource_requirement = hints.get('ResourceRequirement')
    if resource_requirement is None:
        return 0

    cores_min = resource_requirement.get('coresMin')
    cores_max = resource_requirement.get('coresMax')

    if cores_min is not None:
        return cores_min
    if cores_max is not None:
        return cores_max
    return 0


def get_secondary_files(secondary_files):
    """Parses a list of secondary files, recursively.

    Args:
        secondary_files (list): A list of values from a CWL \
                secondaryFiles attribute.

    Returns:
        ([InputFile]): A list of secondary input files.
    """
    result = []
    for value in secondary_files:
        if isinstance(value, dict):
            if 'class' in value and value['class'] == 'File':
                new_file = InputFile(None, value['location'], None, [])
                if 'secondaryFiles' in value:
                    new_file.secondary_files = get_secondary_files(value['secondaryFiles'])
                result.append(new_file)
            elif 'class' in value and value['class'] == 'Directory':
                raise RuntimeError("Directory inputs are not yet supported, sorry")
            else:
                raise RuntimeError("Invalid secondaryFiles entry: must be a File or a Directory")
    return result


def get_files_from_binding(cwl_binding):
    """Parses a CWL input or output binding an returns a list
    containing name: path pairs. Any non-File objects are
    omitted.

    Args:
        cwl_binding (Dict): A dict structure parsed from a JSON CWL binding

    Returns:
        [InputFile]: A list of InputFile objects describing the input \
                files described in the binding.
    """
    result = []
    if cwl_binding is not None:
        for name, value in cwl_binding.items():
            if isinstance(value, dict) and value.get('class') == 'File':
                secondary_files = get_secondary_files(value.get('secondaryFiles', []))
                result.append(InputFile(name, value['location'], None, secondary_files))
            elif isinstance(value, list):
                for i, val in enumerate(value):
                    if isinstance(val, dict) and val.get('class') == 'File':
                        secondary_files = get_secondary_files(val.get('secondaryFiles', []))
                        input_file = InputFile(name, val['location'], None, secondary_files, i)
                        result.append(input_file)

    return result


def get_cwltool_result(cwltool_log):
    """Parses cwltool log output and returns a JobState object
    describing the outcome of the cwl execution.

    Args:
        cwltool_log (str): The standard error output of cwltool

    Returns:
        JobState: Any of JobState.PERMANENT_FAILURE,
        JobState.TEMPORARY_FAILURE or JobState.SUCCESS, or
        JobState.SYSTEM_ERROR if the output could not be interpreted.
    """
    if 'Tool definition failed validation:' in cwltool_log:
        return JobState.PERMANENT_FAILURE
    if 'Final process status is permanentFail' in cwltool_log:
        return JobState.PERMANENT_FAILURE
    elif 'Final process status is temporaryFail' in cwltool_log:
        return JobState.TEMPORARY_FAILURE
    elif 'Final process status is success' in cwltool_log:
        return JobState.SUCCESS

    return JobState.SYSTEM_ERROR
