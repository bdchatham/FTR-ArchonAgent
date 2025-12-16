import * as cdk from 'aws-cdk-lib';
import { ArchonPipelineStack, ArchonPipelineStackProps } from '../lib/archon-pipeline-stack';
import { test } from 'node:test';
import * as assert from 'node:assert';

/**
 * Integration test for pipeline stack synthesis
 * 
 * Validates Requirements: 1.1, 1.3, 1.5, 8.1
 * - 1.1: Stack synthesizes and creates CDK stack with AphexPipelineStack construct
 * - 1.3: Stack creates isolated pipeline resources
 * - 1.5: Stack outputs include webhook URL and artifact bucket name
 * - 8.1: Stack creates S3 bucket for artifacts
 * 
 * Note: These tests verify the ArchonPipelineStack wrapper configuration.
 * Full end-to-end synthesis testing requires the AphexPipeline construct's
 * template files to be properly installed, which happens during actual deployment.
 */

test('Stack instantiation with required parameters succeeds', () => {
  // Create CDK app
  const app = new cdk.App();

  // Create stack with valid configuration - should not throw
  const stack = new ArchonPipelineStack(app, 'TestArchonPipelineStack', {
    clusterName: 'test-arbiter-cluster',
    githubOwner: 'test-owner',
    githubRepo: 'test-repo',
    githubTokenSecretName: 'test-github-token',
    env: {
      account: '123456789012',
      region: 'us-east-1',
    },
  });

  // Verify stack was created
  assert.ok(stack, 'Stack should be instantiated');
  assert.strictEqual(stack.stackName, 'TestArchonPipelineStack', 'Stack name should match');
});

test('Stack properties are correctly configured', () => {
  const app = new cdk.App();

  const props: ArchonPipelineStackProps = {
    clusterName: 'test-arbiter-cluster',
    githubOwner: 'test-owner',
    githubRepo: 'test-repo',
    githubBranch: 'main',
    githubTokenSecretName: 'test-github-token',
    workflowTemplateName: 'test-workflow',
    eventSourceName: 'test-eventsource',
    sensorName: 'test-sensor',
    artifactBucketName: 'test-artifacts',
    artifactRetentionDays: 30,
    env: {
      account: '123456789012',
      region: 'us-east-1',
    },
  };

  const stack = new ArchonPipelineStack(app, 'TestArchonPipelineStack', props);

  // Verify stack accepts all configuration parameters
  assert.ok(stack, 'Stack should be created with all parameters');
  assert.ok(stack.webhookUrl, 'Stack should have webhookUrl output');
  assert.ok(stack.artifactBucketName, 'Stack should have artifactBucketName output');
});

test('Stack outputs are defined with correct properties', () => {
  const app = new cdk.App();

  const stack = new ArchonPipelineStack(app, 'TestArchonPipelineStack', {
    clusterName: 'test-arbiter-cluster',
    githubOwner: 'test-owner',
    githubRepo: 'test-repo',
    githubTokenSecretName: 'test-github-token',
    env: {
      account: '123456789012',
      region: 'us-east-1',
    },
  });

  // Verify output objects exist
  assert.ok(stack.webhookUrl, 'WebhookUrl output should be defined');
  assert.ok(stack.artifactBucketName, 'ArtifactBucketName output should be defined');

  // Verify outputs have correct descriptions
  assert.strictEqual(
    stack.webhookUrl.description,
    'GitHub webhook URL for triggering pipeline executions',
    'WebhookUrl should have correct description'
  );
  assert.strictEqual(
    stack.artifactBucketName.description,
    'S3 bucket name for storing build artifacts',
    'ArtifactBucketName should have correct description'
  );

  // Verify outputs are exported
  assert.ok(
    stack.webhookUrl.exportName?.includes('WebhookUrl'),
    'WebhookUrl should be exported with correct name'
  );
  assert.ok(
    stack.artifactBucketName.exportName?.includes('ArtifactBucketName'),
    'ArtifactBucketName should be exported with correct name'
  );
});

test('Stack uses default values when optional props are not provided', () => {
  const app = new cdk.App();

  // Create stack with only required props
  const stack = new ArchonPipelineStack(app, 'TestArchonPipelineStack', {
    clusterName: 'test-arbiter-cluster',
    githubOwner: 'test-owner',
    githubRepo: 'test-repo',
    githubTokenSecretName: 'test-github-token',
    env: {
      account: '123456789012',
      region: 'us-east-1',
    },
  });

  // Should instantiate without errors even with minimal props
  assert.ok(stack, 'Stack should be created with default values');

  // Verify outputs still exist with defaults
  assert.ok(stack.webhookUrl, 'WebhookUrl output should exist with defaults');
  assert.ok(stack.artifactBucketName, 'ArtifactBucketName output should exist with defaults');
});

test('Stack accepts custom resource names', () => {
  const app = new cdk.App();

  const customWorkflowName = 'custom-workflow-template';
  const customEventSourceName = 'custom-event-source';
  const customSensorName = 'custom-sensor';
  const customBucketName = 'custom-artifact-bucket';

  const stack = new ArchonPipelineStack(app, 'TestArchonPipelineStack', {
    clusterName: 'test-arbiter-cluster',
    githubOwner: 'test-owner',
    githubRepo: 'test-repo',
    githubTokenSecretName: 'test-github-token',
    workflowTemplateName: customWorkflowName,
    eventSourceName: customEventSourceName,
    sensorName: customSensorName,
    artifactBucketName: customBucketName,
    artifactRetentionDays: 60,
    env: {
      account: '123456789012',
      region: 'us-east-1',
    },
  });

  // Should instantiate without errors with custom names
  assert.ok(stack, 'Stack should be created with custom resource names');
});

test('Stack accepts different GitHub branches', () => {
  const app = new cdk.App();

  const stack = new ArchonPipelineStack(app, 'TestArchonPipelineStack', {
    clusterName: 'test-arbiter-cluster',
    githubOwner: 'test-owner',
    githubRepo: 'test-repo',
    githubBranch: 'develop',
    githubTokenSecretName: 'test-github-token',
    env: {
      account: '123456789012',
      region: 'us-east-1',
    },
  });

  // Should instantiate without errors with different branch
  assert.ok(stack, 'Stack should be created with custom branch');
});

test('Stack validates required parameters', () => {
  const app = new cdk.App();

  // Test missing clusterName
  assert.throws(
    () => {
      new ArchonPipelineStack(app, 'TestStack1', {
        clusterName: '',
        githubOwner: 'test-owner',
        githubRepo: 'test-repo',
        githubTokenSecretName: 'test-token',
        env: { account: '123456789012', region: 'us-east-1' },
      });
    },
    'Should throw error when clusterName is empty'
  );

  // Test missing githubOwner
  assert.throws(
    () => {
      new ArchonPipelineStack(app, 'TestStack2', {
        clusterName: 'test-cluster',
        githubOwner: '',
        githubRepo: 'test-repo',
        githubTokenSecretName: 'test-token',
        env: { account: '123456789012', region: 'us-east-1' },
      });
    },
    'Should throw error when githubOwner is empty'
  );

  // Test missing githubRepo
  assert.throws(
    () => {
      new ArchonPipelineStack(app, 'TestStack3', {
        clusterName: 'test-cluster',
        githubOwner: 'test-owner',
        githubRepo: '',
        githubTokenSecretName: 'test-token',
        env: { account: '123456789012', region: 'us-east-1' },
      });
    },
    'Should throw error when githubRepo is empty'
  );

  // Test missing githubTokenSecretName
  assert.throws(
    () => {
      new ArchonPipelineStack(app, 'TestStack4', {
        clusterName: 'test-cluster',
        githubOwner: 'test-owner',
        githubRepo: 'test-repo',
        githubTokenSecretName: '',
        env: { account: '123456789012', region: 'us-east-1' },
      });
    },
    'Should throw error when githubTokenSecretName is empty'
  );
});
