"""Lambda handler for document monitoring."""

import json
import logging
import os
import sys
from datetime import datetime, timezone

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config.config_manager import ConfigManager
from git.github_client import GitHubClient
from storage.change_tracker import ChangeTracker
from ingestion.ingestion_pipeline import IngestionPipeline
from storage.vector_store_manager import VectorStoreManager
from monitor.document_monitor import DocumentMonitor

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    Lambda handler for document monitoring cron job.
    
    Args:
        event: EventBridge event
        context: Lambda context
        
    Returns:
        Response with monitoring results
    """
    try:
        logger.info("Document monitor Lambda invoked")
        
        # Load configuration
        config_path = os.environ.get('CONFIG_PATH', '/var/task/config/config.yaml')
        config_manager = ConfigManager()
        config = config_manager.load_config(config_path)
        
        logger.info(f"Loaded configuration with {len(config.repositories)} repositories")
        
        # Initialize components
        github_token = os.environ.get('GITHUB_TOKEN')
        github_client = GitHubClient(access_token=github_token)
        
        dynamodb_table = os.environ.get('DYNAMODB_TABLE', 'archon-document-tracker')
        change_tracker = ChangeTracker(table_name=dynamodb_table)
        
        opensearch_endpoint = os.environ.get('OPENSEARCH_ENDPOINT')
        opensearch_index = os.environ.get('OPENSEARCH_INDEX', 'archon-documents')
        vector_store = VectorStoreManager(
            opensearch_endpoint=opensearch_endpoint,
            index_name=opensearch_index
        )
        
        ingestion_pipeline = IngestionPipeline(
            embedding_model=config.models.embedding_model,
            vector_store=vector_store
        )
        
        # Create and execute monitor
        monitor = DocumentMonitor(
            config=config,
            github_client=github_client,
            change_tracker=change_tracker,
            ingestion_pipeline=ingestion_pipeline
        )
        
        result = monitor.execute()
        
        # Format response
        response = {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Monitoring execution completed',
                'repositories_checked': result.repositories_checked,
                'documents_processed': result.documents_processed,
                'documents_updated': result.documents_updated,
                'errors': result.errors,
                'execution_time': result.execution_time,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        }
        
        logger.info(f"Monitoring completed successfully: {result}")
        
        return response
        
    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}", exc_info=True)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': 'Monitoring execution failed',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        }
