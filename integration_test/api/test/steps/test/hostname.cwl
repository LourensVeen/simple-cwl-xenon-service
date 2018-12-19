#!/usr/bin/env cwl-runner

cwlVersion: v1.0

class: CommandLineTool
baseCommand: $CERISE_PROJECT_FILES/hostname.sh

inputs: []

stdout: output.txt
outputs:
  output:
    type: File
    outputBinding: { glob: output.txt }
