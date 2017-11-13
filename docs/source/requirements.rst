Requirements
============

Introduction
------------

This document describes the requirements placed on Cerise.  The aim of this
project is to implement all these features, but in a minimal fashion, and with
the intent of eventually replacing this implementation with a more robust
service, probably written in Java. For the time being however, it does need to
work well enough that we can test the rest of our system with it.

Overview
--------

Cerise provides a REST interface through which CWL workflows can be submitted
for execution on a compute resource. The particulars of the compute resource are
configurable, with support for local execution as well as SSH-accessed remote
machines, and compute clusters using SLURM or TORQUE as their resource manager.
There will not be complete support for all possible CWL workflows; in particular
the number of input and output types will be limited.

The requirements below are categorised using the MoSCoW system: as either a
Must have, Should have, Could have or Won't have requirement.

Functionality
-------------

Basic functional requirements
.............................

-   [M] A user can submit a CWL workflow for execution using the `Netherlands
    eScience Center version of the GA4GH workflow execution schema`_ (the REST
    API).

-   [M] Multiple workflows can be submitted and executing at the same time.

-   [M] The service will execute the submitted workflow on a compute resource.

-   [M] The results of the workflow will be available through the REST API.

-   [M] Results may be left on the compute resource by copying them to a storage
    location on the compute resource using explicit commands that are part of
    the CWL workflow.

-   [W] Only a limited subset of CWL files will be supported. The exact subset
    is currently undefined, but supported input and output types will be
    limited.

Compute resources
.................

-   [M] It must be possible to configure the service to select one compute
    resource on which submitted CWL workflows are to be run.

-   [M] Remote execution on a compute resource using either SLURM or
    TORQUE must be supported.

-   [S] Remote machines accessible through SSH should be supported

-   [S] Local execution (on the machine the service runs on) should be
    supported.

Deployment options
..................

-   At least the following deployment configurations must be supported:

    -   [S] Client, this service, and workflow execution all on the same machine
    -   [S] Client on one machine, service and execution on another, where the
        client can connect to the service, but not vice versa.
    -   [M] Client, this service, and workflow execution each on a different
        machine or resource, where the client can connect to the service, and the
        service can connect to the compute resource, but no other connections are
        possible.

.. _`Netherlands eScience Center version of the GA4GH workflow execution schema`: https://github.com/NLeSC/workflow-execution-schemas
