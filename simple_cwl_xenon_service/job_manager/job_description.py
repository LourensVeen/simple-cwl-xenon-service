import json

class JobDescription:
    """Class JobDescription

    Describes a job as it is requested to be run by the client.
    """
    def __init__(self, name, workflow, input):
        """Create a new JobDescription.

        Args:
            name (str): A string containing the name of the job
            workflow (str): A string containing a URL pointing to the workflow
            input (str): A string containing a json description of the input object,
                or an object, which will be converted to a json string.
        """
        self.name = name
        self.workflow = workflow

        if type(input) is str:
            self.input = input
        else:
            self.input = json.dumps(input)
