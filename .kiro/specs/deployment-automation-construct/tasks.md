# Implementation Plan

## Note on Implementation Approach

The `@bdchatham/aphex-pipeline` construct handles configuration parsing, validation, WorkflowTemplate generation, and Kubernetes resource creation internally. Our implementation focuses on:
1. Wrapping the construct with ArchonAgent-specific configuration
2. Creating the aphex-config.yaml file
3. Testing the integration
4. Documenting deployment procedures

Tasks 4-10 from the original plan are handled by the construct itself and do not need separate implementation.

---

- [x] 1. Set up pipeline project structure
  - Create pipeline directory with bin and lib subdirectories
  - Create pipeline/package.json with dependencies (aws-cdk-lib, constructs, @bdchatham/aphex-pipeline)
  - Create pipeline/tsconfig.json with TypeScript configuration
  - Create aphex-config.yaml at repository root with dev environment configuration
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 2. Implement pipeline stack wrapper
  - [x] 2.1 Create ArchonPipelineStack class
    - Implement CDK stack extending cdk.Stack
    - Instantiate AphexPipelineStack construct with configuration parameters
    - Configure cluster name, GitHub repository details, and resource names
    - Set up artifact bucket configuration with retention policy
    - Define stack outputs for webhook URL and artifact bucket name
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 8.1_

- [x] 3. Implement pipeline CDK app
  - [x] 3.1 Create pipeline entry point
    - Create pipeline/bin/pipeline.ts with CDK app initialization
    - Instantiate ArchonPipelineStack with environment configuration
    - Apply tags for resource management (Project, ManagedBy, Environment)
    - Configure CDK app synthesis
    - _Requirements: 1.1, 9.3_

- [x] 4. Create aphex-config.yaml
  - Define version as "1.0"
  - Add build commands (npm install, npm run build, npm test)
  - Define dev environment with region, account, and stacks
  - Add ArchonInfrastructureStack, ArchonKnowledgeBaseStack, ArchonAgentStack, ArchonMonitoringDashboard in dependency order
  - Add optional test commands for dev environment
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 9.4_
  - _Note: The construct validates this file against its internal schema_

- [x] 5. Test pipeline stack synthesis
  - [x] 5.1 Write integration test for stack synthesis
    - Verify stack synthesizes without errors
    - Verify CloudFormation template contains expected resources
    - Verify stack outputs are correctly defined
    - _Requirements: 1.1, 1.3, 1.5, 8.1_

- [ ] 6. Deploy to test environment
  - [ ] 6.1 Set up test prerequisites
    - Ensure EKS cluster with Argo Workflows/Events is available
    - Create GitHub token in AWS Secrets Manager
    - Bootstrap AWS account for CDK
    - _Requirements: 9.1, 9.2_

  - [ ] 6.2 Deploy pipeline stack
    - Run `cdk synth` to verify synthesis
    - Run `cdk deploy` to deploy pipeline infrastructure
    - Verify all resources created successfully
    - _Requirements: 1.1, 1.3, 1.5_

  - [ ] 6.3 Configure GitHub webhook
    - Get webhook URL from stack outputs
    - Configure webhook in GitHub repository
    - Test webhook delivery
    - _Requirements: 3.1, 3.2_

  - [ ] 6.4 Trigger test workflow
    - Push commit to trigger pipeline
    - Monitor workflow execution in Argo UI
    - Verify all stages execute successfully
    - Verify application stacks deploy to dev environment
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 7. Create deployment documentation
  - [ ] 7.1 Document prerequisites
    - List required infrastructure (EKS cluster, Argo Workflows/Events)
    - Document AWS account requirements
    - Document GitHub token requirements
    - _Requirements: 9.5_

  - [ ] 7.2 Document setup steps
    - Document how to install dependencies
    - Document how to configure GitHub token in Secrets Manager
    - Document how to bootstrap AWS account
    - Document how to configure aphex-config.yaml
    - _Requirements: 9.5_

  - [ ] 7.3 Document deployment process
    - Document CDK synthesis command
    - Document CDK deployment command
    - Document how to configure GitHub webhook
    - Document how to trigger first workflow
    - _Requirements: 9.5_

  - [ ] 7.4 Document monitoring procedures
    - Document how to access Argo Workflows UI
    - Document kubectl commands for inspecting resources
    - Document CloudWatch logs and metrics
    - _Requirements: 9.5, 10.1, 10.2_

  - [ ] 7.5 Document troubleshooting
    - Document common deployment failures
    - Document how to check CloudFormation events
    - Document how to check workflow logs
    - Document how to rollback deployments
    - _Requirements: 9.5, 10.3, 10.4_

- [ ] 8. Checkpoint - Verify end-to-end functionality
  - Ensure pipeline deploys successfully
  - Ensure workflows trigger on code changes
  - Ensure application stacks deploy correctly
  - Ensure tests run after deployment
  - Ask the user if questions arise

## Completed Tasks (Handled by AphexPipeline Construct)

The following functionality is provided by the `@bdchatham/aphex-pipeline` construct and does not require separate implementation:

- ✅ Configuration parsing and validation (construct handles internally)
- ✅ WorkflowTemplate generation (construct handles internally)
- ✅ Sensor and EventSource creation (construct handles internally)
- ✅ Test stage generation (construct handles internally)
- ✅ Artifact management (construct handles internally)
- ✅ Self-modification capability (construct handles internally)
- ✅ Stack output capture (construct handles internally)
- ✅ Cross-account deployment support (construct handles internally)

