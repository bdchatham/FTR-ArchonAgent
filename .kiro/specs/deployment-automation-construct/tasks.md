# Implementation Plan

- [ ] 1. Set up pipeline project structure
  - Create pipeline directory with bin and lib subdirectories
  - Create pipeline/package.json with dependencies (aws-cdk-lib, constructs, @bdchatham/aphex-pipeline, js-yaml, @kubernetes/client-node)
  - Create pipeline/tsconfig.json with TypeScript configuration
  - Create aphex-config.yaml at repository root with dev environment configuration
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [ ] 2. Implement pipeline stack
  - [ ] 2.1 Create ArchonPipelineStack class
    - Implement CDK stack extending cdk.Stack
    - Instantiate AphexPipelineStack construct with configuration parameters
    - Configure cluster name, GitHub repository details, and resource names
    - Set up artifact bucket configuration with retention policy
    - Define stack outputs for webhook URL and artifact bucket name
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 8.1_

  - [ ] 2.2 Write property test for stack synthesis
    - **Property 1: Stack synthesis completeness**
    - **Validates: Requirements 1.1, 1.3, 1.5, 8.1**

  - [ ] 2.3 Write property test for configuration parameters
    - **Property 2: Configuration parameter acceptance**
    - **Validates: Requirements 1.2**

  - [ ] 2.4 Write property test for cluster reference
    - **Property 3: Cluster reference correctness**
    - **Validates: Requirements 1.4**

- [ ] 3. Implement pipeline CDK app
  - [ ] 3.1 Create pipeline entry point
    - Create pipeline/bin/pipeline.ts with CDK app initialization
    - Instantiate ArchonPipelineStack with environment configuration
    - Apply tags for resource management (Project, ManagedBy, Environment)
    - Configure CDK app synthesis
    - _Requirements: 1.1, 9.3_

- [ ] 4. Implement configuration system
  - [ ] 4.1 Define configuration interfaces
    - Create TypeScript interfaces for AphexConfig, BuildConfig, EnvironmentConfig, StackConfig, TestConfig
    - Add type definitions for all configuration fields
    - _Requirements: 2.1, 2.3_

  - [ ] 4.2 Implement configuration validator
    - Create configuration validation function using JSON Schema
    - Validate version, build commands, environment structure
    - Validate stack dependencies are acyclic
    - Validate AWS account IDs and region formats
    - Return descriptive error messages for validation failures
    - _Requirements: 2.1, 2.3_

  - [ ] 4.3 Write property test for configuration validation
    - **Property 4: Configuration schema validation**
    - **Validates: Requirements 2.1, 2.3**

  - [ ] 4.4 Implement configuration parser
    - Create function to parse aphex-config.yaml using js-yaml
    - Handle parsing errors with clear error messages
    - Return typed configuration object
    - _Requirements: 2.1_

- [ ] 5. Implement WorkflowTemplate generation
  - [ ] 5.1 Create WorkflowTemplate generator
    - Implement function to generate Argo WorkflowTemplate from configuration
    - Generate validation stage with config/credentials/CDK context checks
    - Generate build stage with clone, install, build, test, and artifact upload steps
    - Generate pipeline deployment stage with WorkflowTemplate regeneration and apply steps
    - Generate dev environment deployment stage with artifact download, AWS context, stack synthesis, and deployment steps
    - Generate dev test stage if test commands are defined
    - _Requirements: 2.2, 2.5, 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ] 5.2 Implement stack dependency ordering
    - Create topological sort function for stack dependencies
    - Detect circular dependencies and return error
    - Generate deployment steps in correct dependency order
    - _Requirements: 2.4_

  - [ ] 5.3 Write property test for dependency ordering
    - **Property 5: Stack dependency ordering**
    - **Validates: Requirements 2.4**

  - [ ] 5.4 Write property test for WorkflowTemplate completeness
    - **Property 6: WorkflowTemplate stage completeness**
    - **Validates: Requirements 2.2, 2.5, 4.1, 4.2, 4.5**

  - [ ] 5.5 Write property test for stage ordering
    - **Property 8: Stage execution ordering**
    - **Validates: Requirements 4.3, 4.4**

- [ ] 6. Implement Sensor configuration
  - [ ] 6.1 Create Sensor generator
    - Generate Argo Events Sensor configuration
    - Configure branch filter for configured branch
    - Add parameter mappings for commit SHA and repository information
    - Configure workflow trigger from WorkflowTemplate
    - _Requirements: 3.3, 3.4_

  - [ ] 6.2 Write property test for Sensor configuration
    - **Property 7: Sensor configuration correctness**
    - **Validates: Requirements 3.3, 3.4**

- [ ] 7. Implement test stage generation
  - [ ] 7.1 Create test stage generator
    - Generate test stage for environments with test commands
    - Place test stage immediately after deployment stage
    - Execute test commands in configuration order
    - Configure failure propagation to stop workflow on test failure
    - Add stage dependencies to ensure correct execution order
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ] 7.2 Write property test for test stage generation
    - **Property 9: Test stage generation**
    - **Validates: Requirements 5.1**

  - [ ] 7.3 Write property test for test command ordering
    - **Property 10: Test command ordering**
    - **Validates: Requirements 5.2**

  - [ ] 7.4 Write property test for failure propagation
    - **Property 11: Workflow failure propagation**
    - **Validates: Requirements 5.3, 5.4**

- [ ] 8. Implement artifact management
  - [ ] 8.1 Configure S3 bucket in pipeline stack
    - Add S3 bucket resource to pipeline stack
    - Configure bucket encryption
    - Add lifecycle policy for artifact retention
    - Configure bucket permissions for workflow execution role
    - _Requirements: 8.1, 8.3_

  - [ ] 8.2 Implement artifact upload in build stage
    - Add artifact upload steps to build stage
    - Use commit SHA in S3 key path
    - Compress artifacts before upload
    - _Requirements: 8.2_

  - [ ] 8.3 Implement artifact download in deployment stages
    - Add artifact download steps to deployment stages
    - Use same commit SHA parameter as upload
    - Extract artifacts after download
    - _Requirements: 8.4_

  - [ ] 8.4 Write property test for artifact organization
    - **Property 15: Artifact organization**
    - **Validates: Requirements 8.2**

  - [ ] 8.5 Write property test for lifecycle policy
    - **Property 16: Artifact lifecycle policy**
    - **Validates: Requirements 8.3**

  - [ ] 8.6 Write property test for artifact download consistency
    - **Property 17: Artifact download consistency**
    - **Validates: Requirements 8.4**

- [ ] 9. Implement self-modification capability
  - [ ] 9.1 Add self-modification to pipeline deployment stage
    - Add steps to read aphex-config.yaml
    - Add steps to regenerate WorkflowTemplate from configuration
    - Add kubectl apply step to update WorkflowTemplate
    - Configure failure handling to preserve previous WorkflowTemplate
    - _Requirements: 7.2, 7.3, 7.5_

  - [ ] 9.2 Write property test for self-modification
    - **Property 14: Self-modification capability**
    - **Validates: Requirements 7.2, 7.3, 7.5**

- [ ] 10. Implement stack output capture
  - [ ] 10.1 Add output capture to deployment stages
    - Add steps to capture CloudFormation stack outputs
    - Store outputs for use by dependent stacks
    - Pass outputs between deployment steps
    - _Requirements: 6.4_

  - [ ] 10.2 Write property test for output capture
    - **Property 13: Stack output capture**
    - **Validates: Requirements 6.4**

- [ ] 11. Create example aphex-config.yaml
  - Define version as "1.0"
  - Add build commands (npm install, npm run build, npm test)
  - Define dev environment with region, account, and stacks
  - Add ArchonInfrastructureStack, ArchonKnowledgeBaseStack, ArchonAgentStack, ArchonMonitoringDashboard
  - Configure stack dependencies (KnowledgeBase depends on Infrastructure, Agent depends on KnowledgeBase, Monitoring depends on Agent)
  - Add optional test commands for dev environment
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 9.4_

- [ ] 12. Create deployment documentation
  - Document prerequisites (Arbiter Pipeline Infrastructure, GitHub token, AWS account)
  - Document setup steps (install dependencies, configure GitHub token, bootstrap AWS account)
  - Document deployment process (synthesize, deploy, configure webhook)
  - Document monitoring procedures (Argo UI, kubectl commands, CloudWatch)
  - Document troubleshooting steps for common issues
  - _Requirements: 9.5_

- [ ] 13. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
