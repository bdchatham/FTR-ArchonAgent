"""GitHub client for fetching repository documents."""

import asyncio
from typing import List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import structlog
from github import Github
from github.GithubException import GithubException

logger = structlog.get_logger()


@dataclass
class Document:
    """Represents a document from a GitHub repository."""
    repo_url: str
    file_path: str
    content: str
    sha: str
    last_modified: datetime
    document_type: str = "kiro_doc"
    source_type: str = "github"


class GitHubClient:
    """Client for fetching documents from GitHub repositories."""
    
    def __init__(self, github_token: str):
        """Initialize GitHub client."""
        self.github = Github(github_token) if github_token else Github()
        self.rate_limit_delay = 1.0  # Base delay for rate limiting
    
    async def fetch_documents(
        self, 
        repo_url: str, 
        branch: str = "main", 
        path: str = ".kiro/docs"
    ) -> List[Document]:
        """
        Fetch documents from a GitHub repository path.
        
        Args:
            repo_url: GitHub repository URL
            branch: Branch to fetch from
            path: Path within repository to fetch
            
        Returns:
            List of Document objects
        """
        try:
            # Extract owner/repo from URL
            repo_parts = repo_url.replace("https://github.com/", "").split("/")
            if len(repo_parts) < 2:
                raise ValueError(f"Invalid repository URL: {repo_url}")
            
            owner, repo_name = repo_parts[0], repo_parts[1]
            
            logger.info("Fetching documents", 
                       owner=owner, 
                       repo=repo_name, 
                       branch=branch, 
                       path=path)
            
            # Get repository
            repo = self.github.get_repo(f"{owner}/{repo_name}")
            
            # Get contents of the path
            documents = []
            try:
                contents = repo.get_contents(path, ref=branch)
                
                # Handle both single file and directory
                if not isinstance(contents, list):
                    contents = [contents]
                
                for content in contents:
                    if content.type == "file" and content.name.endswith(".md"):
                        doc = await self._create_document(repo_url, content)
                        documents.append(doc)
                    elif content.type == "dir":
                        # Recursively fetch from subdirectories
                        subdocs = await self._fetch_directory_documents(
                            repo_url, repo, content.path, branch
                        )
                        documents.extend(subdocs)
                        
            except GithubException as e:
                if e.status == 404:
                    logger.warning("Path not found", repo_url=repo_url, path=path)
                    return []
                raise
            
            logger.info("Documents fetched", 
                       repo_url=repo_url, 
                       document_count=len(documents))
            
            return documents
            
        except Exception as e:
            logger.error("Failed to fetch documents", 
                        repo_url=repo_url, 
                        error=str(e))
            raise
    
    async def _fetch_directory_documents(
        self, 
        repo_url: str, 
        repo, 
        dir_path: str, 
        branch: str
    ) -> List[Document]:
        """Recursively fetch documents from a directory."""
        documents = []
        
        try:
            contents = repo.get_contents(dir_path, ref=branch)
            if not isinstance(contents, list):
                contents = [contents]
            
            for content in contents:
                if content.type == "file" and content.name.endswith(".md"):
                    doc = await self._create_document(repo_url, content)
                    documents.append(doc)
                elif content.type == "dir":
                    subdocs = await self._fetch_directory_documents(
                        repo_url, repo, content.path, branch
                    )
                    documents.extend(subdocs)
                    
                # Add small delay to avoid rate limiting
                await asyncio.sleep(0.1)
                
        except GithubException as e:
            if e.status == 403:
                # Rate limited - exponential backoff
                logger.warning("Rate limited, backing off", delay=self.rate_limit_delay)
                await asyncio.sleep(self.rate_limit_delay)
                self.rate_limit_delay *= 2
                # Retry once
                return await self._fetch_directory_documents(repo_url, repo, dir_path, branch)
            raise
        
        return documents
    
    async def _create_document(self, repo_url: str, content) -> Document:
        """Create Document object from GitHub content."""
        # Decode content
        file_content = content.decoded_content.decode('utf-8')
        
        # Get last modified time (use commit date if available)
        last_modified = datetime.now()
        if hasattr(content, 'last_modified') and content.last_modified:
            last_modified = content.last_modified
        
        return Document(
            repo_url=repo_url,
            file_path=content.path,
            content=file_content,
            sha=content.sha,
            last_modified=last_modified,
            document_type="kiro_doc",
            source_type="github"
        )
