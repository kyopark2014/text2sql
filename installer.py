#!/usr/bin/env python3
"""
AWS Infrastructure Installer using boto3
This script creates AWS infrastructure resources equivalent to the CDK stack.
"""

import boto3
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
from botocore.exceptions import ClientError

# Configuration
project_name = "textsql" # at least 3 characters
region = "us-west-2"
git_name = "textsql"
cloudfront_comment = "CloudFront-for-rag-project"

sts_client = boto3.client("sts", region_name=region)
account_id = sts_client.get_caller_identity()["Account"]

vector_index_name = project_name
vector_bucket_name = f"{project_name}-{account_id}"
embedding_dimensions = 1024
embedding_data_type = "float32"
distance_metric = "cosine"

# Bedrock Knowledge Base requires these metadata keys as non-filterable on S3 Vectors index
BEDROCK_NON_FILTERABLE_METADATA_KEYS = [
    "AMAZON_BEDROCK_TEXT",
    "AMAZON_BEDROCK_METADATA",
]

# Initialize boto3 clients
s3_client = boto3.client("s3", region_name=region)
iam_client = boto3.client("iam", region_name=region)
secrets_client = boto3.client("secretsmanager", region_name=region)
s3vectors_client = boto3.client("s3vectors", region_name=region)
cloudfront_client = boto3.client("cloudfront", region_name=region)

bucket_name = f"storage-for-rag-project-{account_id}-{region}"


def s3_vectors_bucket_arn(bucket_name: str = vector_bucket_name) -> str:
    """ARN for an S3 vector bucket."""
    return f"arn:aws:s3vectors:{region}:{account_id}:bucket/{bucket_name}"


def s3_vectors_index_arn(
    index_name: str = vector_index_name,
    bucket_name: str = vector_bucket_name,
) -> str:
    """ARN for a vector index within an S3 vector bucket."""
    return f"{s3_vectors_bucket_arn(bucket_name)}/index/{index_name}"


# Configure logging
def setup_logging(log_level=logging.INFO):
    """Setup logging configuration."""
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(),
            # logging.FileHandler(f"installer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        ]
    )
    
    return logging.getLogger(__name__)


logger = setup_logging()


def create_s3_bucket() -> str:
    """Create S3 bucket with CORS configuration."""
    logger.info(f"[2/6] Creating S3 bucket: {bucket_name}")
    
    try:
        # Create bucket
        logger.debug(f"Creating bucket in region: {region}")
        if region == "us-east-1":
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region}
            )
        logger.debug("Bucket created successfully")
        
        # Configure bucket
        logger.debug("Configuring public access block")
        s3_client.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True
            }
        )
        
        # Set CORS configuration
        logger.debug("Setting CORS configuration")
        cors_configuration = {
            "CORSRules": [
                {
                    "AllowedHeaders": ["*"],
                    "AllowedMethods": ["GET", "POST", "PUT"],
                    "AllowedOrigins": ["*"]
                }
            ]
        }
        s3_client.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration=cors_configuration
        )
        
        # Enable versioning (set to false means suspend)
        logger.debug("Configuring versioning")
        s3_client.put_bucket_versioning(
            Bucket=bucket_name,
            VersioningConfiguration={"Status": "Suspended"}
        )
        
        # Create docs folder
        logger.debug("Creating docs folder")
        try:
            s3_client.put_object(
                Bucket=bucket_name,
                Key="docs/",
                Body=b""
            )
            logger.debug("docs folder created successfully")
        except ClientError as e:
            logger.warning(f"Failed to create docs folder: {e}")
        
        logger.info(f"✓ S3 bucket created successfully: {bucket_name}")
        return bucket_name
    
    except ClientError as e:
        if e.response["Error"]["Code"] in ["BucketAlreadyExists", "BucketAlreadyOwnedByYou"]:
            logger.warning(f"S3 bucket already exists: {bucket_name}")
            # Create docs folder if bucket already exists
            logger.debug("Creating docs folder in existing bucket")
            try:
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key="docs/",
                    Body=b""
                )
                logger.debug("docs folder created successfully")
            except ClientError as folder_error:
                if folder_error.response["Error"]["Code"] != "NoSuchBucket":
                    logger.warning(f"Failed to create docs folder: {folder_error}")
            return bucket_name
        logger.error(f"Failed to create S3 bucket: {e}")
        raise


def create_iam_role(role_name: str, assume_role_policy: Dict, managed_policies: Optional[List[str]] = None) -> str:
    """Create IAM role."""
    logger.debug(f"Creating IAM role: {role_name}")
    
    try:
        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Description=f"Role for {role_name}"
        )
        role_arn = response["Role"]["Arn"]
        logger.debug(f"Role created: {role_arn}")
        
        if managed_policies:
            logger.debug(f"Attaching {len(managed_policies)} managed policies")
            for policy_arn in managed_policies:
                iam_client.attach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy_arn
                )
                logger.debug(f"Attached policy: {policy_arn}")
        
        logger.info(f"✓ IAM role created: {role_name}")
        return role_arn
    
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            logger.warning(f"IAM role already exists: {role_name}")
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response["Role"]["Arn"]
            
            # Update trust policy for existing role
            try:
                logger.info(f"Updating trust policy for existing role: {role_name}")
                iam_client.update_assume_role_policy(
                    RoleName=role_name,
                    PolicyDocument=json.dumps(assume_role_policy)
                )
                logger.info(f"✓ Updated trust policy for role: {role_name}")
                
                # Verify trust policy was updated correctly
                updated_role = iam_client.get_role(RoleName=role_name)
                policy_doc = updated_role["Role"]["AssumeRolePolicyDocument"]
                # Handle both string and dict formats (boto3 may return either)
                if isinstance(policy_doc, str):
                    updated_policy = json.loads(policy_doc)
                else:
                    updated_policy = policy_doc
                logger.debug(f"Verified trust policy: {json.dumps(updated_policy, indent=2)}")
            except ClientError as trust_policy_error:
                logger.error(f"✗ Failed to update trust policy for role {role_name}: {trust_policy_error}")
                logger.error(f"  Error Code: {trust_policy_error.response.get('Error', {}).get('Code')}")
                logger.error(f"  Error Message: {trust_policy_error.response.get('Error', {}).get('Message')}")
                raise
            
            # Update managed policies if provided
            if managed_policies:
                logger.debug(f"Updating managed policies for existing role")
                # Get currently attached managed policies
                try:
                    attached_policies = iam_client.list_attached_role_policies(RoleName=role_name)
                    current_policy_arns = {policy["PolicyArn"] for policy in attached_policies["AttachedPolicies"]}
                    
                    # Attach missing policies
                    for policy_arn in managed_policies:
                        if policy_arn not in current_policy_arns:
                            iam_client.attach_role_policy(
                                RoleName=role_name,
                                PolicyArn=policy_arn
                            )
                            logger.debug(f"Attached missing policy: {policy_arn}")
                except ClientError as policy_error:
                    logger.warning(f"Could not update managed policies: {policy_error}")
            
            return role_arn
        logger.error(f"Failed to create IAM role {role_name}: {e}")
        raise

def attach_inline_policy(role_name: str, policy_name: str, policy_document: Dict):
    """Attach or update inline policy to IAM role."""
    logger.debug(f"Attaching/updating inline policy {policy_name} to {role_name}")
    
    try:
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_document)
        )
        logger.debug(f"Policy {policy_name} attached/updated successfully")
    except ClientError as e:
        logger.error(f"Error attaching/updating policy {policy_name}: {e}")
        raise

def create_knowledge_base_role() -> str:
    """Create Knowledge Base IAM role."""
    logger.info("[3/6] Creating Knowledge Base IAM role")
    role_name = f"role-knowledge-base-for-{project_name}-{region}"
    
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    role_arn = create_iam_role(role_name, assume_role_policy)
    
    # Always attach/update inline policies (put_role_policy will create or update)
    bedrock_invoke_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:*",
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:GetInferenceProfile",
                    "bedrock:GetFoundationModel"
                ],
                "Resource": [
                    "*",
                    f"arn:aws:bedrock:{region}:{account_id}:inference-profile/*",
                    f"arn:aws:bedrock:{region}:*:inference-profile/*",
                    "arn:aws:bedrock:*::foundation-model/*"
                ]
            }
        ]
    }
    attach_inline_policy(role_name, f"bedrock-invoke-policy-for-{project_name}", bedrock_invoke_policy)
    
    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:*"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"knowledge-base-s3-policy-for-{project_name}", s3_policy)

    # Remove legacy OpenSearch Serverless inline policy if upgrading from a previous install
    try:
        iam_client.delete_role_policy(
            RoleName=role_name,
            PolicyName=f"bedrock-agent-opensearch-policy-for-{project_name}",
        )
    except ClientError:
        pass

    bucket_arn = s3_vectors_bucket_arn()
    s3vectors_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3vectors:GetVectorBucket",
                    "s3vectors:ListVectorBuckets",
                    "s3vectors:GetIndex",
                    "s3vectors:ListIndexes",
                    "s3vectors:QueryVectors",
                    "s3vectors:GetVectors",
                    "s3vectors:PutVectors",
                    "s3vectors:DeleteVectors",
                    "s3vectors:ListVectors",
                ],
                "Resource": [
                    bucket_arn,
                    f"{bucket_arn}/index/*",
                ],
            }
        ],
    }
    attach_inline_policy(role_name, f"bedrock-agent-s3vectors-policy-for-{project_name}", s3vectors_policy)
    
    bedrock_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:*",
                    "bedrock:GetInferenceProfile"
                ],
                "Resource": [
                    "*",
                    f"arn:aws:bedrock:{region}:*:inference-profile/*"
                ]
            }
        ]
    }
    attach_inline_policy(role_name, f"bedrock-agent-bedrock-policy-for-{project_name}", bedrock_policy)

    try:
        iam_client.delete_role_policy(
            RoleName=role_name,
            PolicyName=f"bda-parser-policy-for-{project_name}",
        )
    except ClientError:
        pass

    return role_arn


def create_secrets() -> Dict[str, str]:
    """Create Secrets Manager secrets."""
    logger.info("[1/6] Creating Secrets Manager secrets")
    logger.info("Please enter API keys when prompted (press Enter to skip and leave empty):")
    
    secrets = {
        "weather": {
            "name": f"openweathermap-{project_name}",
            "description": "secret for weather api key",
            "secret_value": {
                "project_name": project_name,
                "weather_api_key": ""
            }
        },
        "tavily": {
            "name": f"tavilyapikey-{project_name}",
            "description": "secret for tavily api key",
            "secret_value": {
                "project_name": project_name,
                "tavily_api_key": ""
            }
        }
    }
    
    secret_arns = {}
    
    for key, secret_config in secrets.items():
        # Check if secret already exists before prompting for input
        try:
            response = secrets_client.describe_secret(SecretId=secret_config["name"])
            secret_arns[key] = response["ARN"]
            logger.warning(f"  Secret already exists: {secret_config['name']}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                # Secret doesn't exist, prompt for API key and create it
                if key == "tavily":
                    logger.info(f"Enter credential of {secret_config['name']} (Tavily API Key):")
                    api_key = input(f"Creating {secret_config['name']} - Tavily API Key: ").strip()
                    secret_config["secret_value"]["tavily_api_key"] = api_key
                
                # Create the secret
                try:
                    response = secrets_client.create_secret(
                        Name=secret_config["name"],
                        Description=secret_config["description"],
                        SecretString=json.dumps(secret_config["secret_value"])
                    )
                    secret_arns[key] = response["ARN"]
                    logger.info(f"  ✓ Created secret: {secret_config['name']}")
                except ClientError as create_error:
                    logger.error(f"  Failed to create secret {secret_config['name']}: {create_error}")
                    raise
            else:
                logger.error(f"  Failed to check secret {secret_config['name']}: {e}")
                raise
    
    logger.info(f"✓ Created {len(secret_arns)} secrets")
    
    return secret_arns


def create_s3_vectors_store() -> Dict[str, str]:
    """Create S3 vector bucket and index for Bedrock Knowledge Base."""
    logger.info("[4/6] Creating S3 Vectors store (vector bucket + index)")

    vector_bucket_arn = s3_vectors_bucket_arn()
    index_arn = s3_vectors_index_arn()

    # Vector bucket
    try:
        s3vectors_client.create_vector_bucket(vectorBucketName=vector_bucket_name)
        logger.info(f"  ✓ Vector bucket created: {vector_bucket_name}")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("ConflictException", "ResourceAlreadyExistsException"):
            logger.warning(f"  Vector bucket already exists: {vector_bucket_name}")
            try:
                existing = s3vectors_client.get_vector_bucket(
                    vectorBucketName=vector_bucket_name
                )
                vector_bucket_arn = existing["vectorBucket"]["vectorBucketArn"]
            except ClientError:
                pass
        else:
            logger.error(f"Failed to create vector bucket: {e}")
            raise

    # Vector index (Bedrock KB requires non-filterable metadata keys)
    try:
        response = s3vectors_client.create_index(
            vectorBucketName=vector_bucket_name,
            indexName=vector_index_name,
            dataType=embedding_data_type,
            dimension=embedding_dimensions,
            distanceMetric=distance_metric,
            metadataConfiguration={
                "nonFilterableMetadataKeys": BEDROCK_NON_FILTERABLE_METADATA_KEYS,
            },
        )
        index_arn = response.get("indexArn", index_arn)
        logger.info(f"  ✓ Vector index created: {vector_index_name}")
        logger.info("  Waiting for vector index to be ready...")
        time.sleep(15)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("ConflictException", "ResourceAlreadyExistsException"):
            logger.warning(f"  Vector index already exists: {vector_index_name}")
            try:
                existing = s3vectors_client.get_index(
                    vectorBucketName=vector_bucket_name,
                    indexName=vector_index_name,
                )
                index_arn = existing["index"]["indexArn"]
            except ClientError:
                pass
        else:
            logger.error(f"Failed to create vector index: {e}")
            raise

    logger.info(f"✓ S3 Vectors store ready")
    logger.info(f"  Vector bucket ARN: {vector_bucket_arn}")
    logger.info(f"  Vector index ARN: {index_arn}")

    return {
        "vectorBucketName": vector_bucket_name,
        "vectorBucketArn": vector_bucket_arn,
        "indexName": vector_index_name,
        "indexArn": index_arn,
    }


def delete_knowledge_base(knowledge_base_id: str) -> None:
    """Delete Knowledge Base and its data sources."""
    bedrock_agent_client = boto3.client("bedrock-agent", region_name=region)
    
    try:
        # Delete all data sources first
        try:
            data_sources = bedrock_agent_client.list_data_sources(
                knowledgeBaseId=knowledge_base_id,
                maxResults=100
            )
            for ds in data_sources.get("dataSourceSummaries", []):
                try:
                    bedrock_agent_client.delete_data_source(
                        knowledgeBaseId=knowledge_base_id,
                        dataSourceId=ds["dataSourceId"]
                    )
                    logger.debug(f"Deleted data source: {ds['dataSourceId']}")
                except Exception as e:
                    logger.warning(f"Failed to delete data source {ds['dataSourceId']}: {e}")
        except Exception as e:
            logger.debug(f"Error listing/deleting data sources: {e}")
        
        # Delete the knowledge base
        bedrock_agent_client.delete_knowledge_base(knowledgeBaseId=knowledge_base_id)
        logger.info(f"Deleted Knowledge Base: {knowledge_base_id}")
        
        # Wait for deletion to complete
        logger.debug("Waiting for Knowledge Base deletion to complete...")
        max_wait = 60  # Wait up to 60 seconds
        waited = 0
        while waited < max_wait:
            try:
                kb_response = bedrock_agent_client.get_knowledge_base(knowledgeBaseId=knowledge_base_id)
                status = kb_response["knowledgeBase"]["status"]
                if status == "DELETED":
                    break
                time.sleep(5)
                waited += 5
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.debug("Knowledge Base deletion confirmed")
                    break
                raise
        
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.debug(f"Knowledge Base {knowledge_base_id} already deleted")
        else:
            logger.error(f"Failed to delete Knowledge Base {knowledge_base_id}: {e}")
            raise


def ensure_data_source(
    bedrock_agent_client,
    knowledge_base_id: str,
    s3_bucket_name: str,
) -> str:
    """Create S3 data source with default parser when missing."""
    data_sources = bedrock_agent_client.list_data_sources(
        knowledgeBaseId=knowledge_base_id,
        maxResults=100,
    )
    for ds in data_sources.get("dataSourceSummaries", []):
        if ds["name"] == s3_bucket_name:
            logger.info(f"  Data source already exists: {ds['dataSourceId']}")
            return ds["dataSourceId"]

    logger.info("  Creating data source with default parser...")
    data_source_response = bedrock_agent_client.create_data_source(
        knowledgeBaseId=knowledge_base_id,
        name=s3_bucket_name,
        description=f"S3 data source: {s3_bucket_name}",
        dataDeletionPolicy="RETAIN",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{s3_bucket_name}",
                "inclusionPrefixes": ["docs/"],
            },
        },
        vectorIngestionConfiguration={
            "chunkingConfiguration": {
                "chunkingStrategy": "FIXED_SIZE",
                "fixedSizeChunkingConfiguration": {
                    "maxTokens": 300,
                    "overlapPercentage": 20,
                },
            },
        },
    )
    data_source_id = data_source_response["dataSource"]["dataSourceId"]
    logger.info(f"  ✓ Data source created: {data_source_id}")
    return data_source_id


def create_knowledge_base_with_s3_vectors(s3_vectors_info: Dict[str, str], knowledge_base_role_arn: str, s3_bucket_name: str) -> str:
    """Create Knowledge Base with S3 Vectors as the vector store."""
    logger.info("[5/6] Creating Knowledge Base with S3 Vectors")
    
    bedrock_agent_client = boto3.client("bedrock-agent", region_name=region)
    
    # Check if Knowledge Base already exists
    try:
        logger.info("  Checking if Knowledge Base already exists...")
        kb_list = bedrock_agent_client.list_knowledge_bases()
        for kb in kb_list.get("knowledgeBaseSummaries", []):
            if kb["name"] == project_name:
                logger.warning(f"Knowledge Base already exists: {kb['knowledgeBaseId']}")
                
                kb_details = bedrock_agent_client.get_knowledge_base(knowledgeBaseId=kb["knowledgeBaseId"])
                storage = kb_details["knowledgeBase"]["storageConfiguration"]
                s3_cfg = storage.get("s3VectorsConfiguration", {})
                kb_index_arn = s3_cfg.get("indexArn")
                storage_type = storage.get("type")

                if storage_type != "S3_VECTORS" or kb_index_arn != s3_vectors_info["indexArn"]:
                    logger.warning("Knowledge Base is not using the expected S3 Vectors index:")
                    logger.warning(f"  Storage type: {storage_type}")
                    logger.warning(f"  Current index ARN: {kb_index_arn}")
                    logger.warning(f"  Expected index ARN: {s3_vectors_info['indexArn']}")

                    delete_knowledge_base(kb["knowledgeBaseId"])
                    break

                logger.info("Knowledge Base is using correct S3 Vectors index")
                knowledge_base_id = kb["knowledgeBaseId"]
                ensure_data_source(
                    bedrock_agent_client, knowledge_base_id, s3_bucket_name
                )
                return knowledge_base_id
        logger.info("  Knowledge Base does not exist. Creating new one...")
    except Exception as e:
        logger.debug(f"Error checking existing Knowledge Base: {e}")
    
    # Verify Knowledge Base role before creating
    logger.info("  Verifying Knowledge Base role configuration...")
    try:
        role_response = iam_client.get_role(RoleName=f"role-knowledge-base-for-{project_name}-{region}")
        policy_doc = role_response["Role"]["AssumeRolePolicyDocument"]
        # Handle both string and dict formats (boto3 may return either)
        if isinstance(policy_doc, str):
            trust_policy = json.loads(policy_doc)
        else:
            trust_policy = policy_doc
        logger.debug(f"  Role trust policy: {json.dumps(trust_policy, indent=2)}")
        
        # Verify trust policy allows bedrock.amazonaws.com
        statements = trust_policy.get("Statement", [])
        bedrock_allowed = False
        for statement in statements:
            if statement.get("Effect") == "Allow":
                principal = statement.get("Principal", {})
                if principal.get("Service") == "bedrock.amazonaws.com":
                    bedrock_allowed = True
                    break
        
        if not bedrock_allowed:
            logger.error("  ✗ Knowledge Base role trust policy does not allow bedrock.amazonaws.com")
            logger.error("  Please update the role trust policy manually or delete and recreate the role")
            raise Exception("Knowledge Base role trust policy is incorrect")
        
        logger.info("  ✓ Knowledge Base role trust policy is correct")
    except ClientError as role_error:
        logger.error(f"  ✗ Failed to verify Knowledge Base role: {role_error}")
        raise
    
    # Create Knowledge Base
    logger.debug(f"Creating Knowledge Base with S3 Vectors index: {s3_vectors_info['indexArn']}")
    response = bedrock_agent_client.create_knowledge_base(
        name=project_name,
        description="Knowledge base with default parser (S3 Vectors)",
        roleArn=knowledge_base_role_arn,
        tags={
            project_name: 'true'
        },
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0",
                "embeddingModelConfiguration": {
                    "bedrockEmbeddingModelConfiguration": {
                        "dimensions": embedding_dimensions,
                        "embeddingDataType": "FLOAT32",
                    }
                },
            }
        },
        storageConfiguration={
            "type": "S3_VECTORS",
            "s3VectorsConfiguration": {
                "vectorBucketArn": s3_vectors_info["vectorBucketArn"],
                "indexArn": s3_vectors_info["indexArn"],
            },
        }
    )
    
    knowledge_base_id = response["knowledgeBase"]["knowledgeBaseId"]
    logger.info(f"✓ Knowledge Base created: {knowledge_base_id}")
    
    # Wait for Knowledge Base to be active
    logger.info("  Waiting for Knowledge Base to be active...")
    while True:
        kb_response = bedrock_agent_client.get_knowledge_base(knowledgeBaseId=knowledge_base_id)
        status = kb_response["knowledgeBase"]["status"]
        
        if status == "ACTIVE":
            logger.info("  Knowledge Base is now active")
            break
        elif status == "FAILED":
            raise Exception("Knowledge Base creation failed")
        
        logger.debug(f"  Knowledge Base status: {status} (waiting...)")
        time.sleep(10)
    
    ensure_data_source(
        bedrock_agent_client, knowledge_base_id, s3_bucket_name
    )

    return knowledge_base_id


def create_cloudfront_distribution(s3_bucket_name: str) -> Dict[str, str]:
    """Create CloudFront distribution with S3 origin."""
    logger.info("[6/6] Creating CloudFront distribution (S3)")
    
    # Check if CloudFront distribution already exists
    try:
        distributions = cloudfront_client.list_distributions()
        for dist in distributions.get("DistributionList", {}).get("Items", []):
            if cloudfront_comment in dist.get("Comment", ""):
                if dist.get("Enabled", False):
                    logger.warning(f"CloudFront distribution already exists: {dist['DomainName']}")
                    return {
                        "id": dist["Id"],
                        "domain": dist["DomainName"]
                    }
                else:
                    # Distribution exists but is disabled, enable it
                    logger.warning(f"CloudFront distribution exists but is disabled: {dist['DomainName']}")
                    logger.info("  Enabling existing CloudFront distribution...")
                    
                    # Get current distribution config
                    dist_config_response = cloudfront_client.get_distribution_config(Id=dist["Id"])
                    dist_config = dist_config_response["DistributionConfig"]
                    etag = dist_config_response["ETag"]
                    
                    # Enable the distribution
                    dist_config["Enabled"] = True
                    
                    # Update the distribution
                    cloudfront_client.update_distribution(
                        Id=dist["Id"],
                        DistributionConfig=dist_config,
                        IfMatch=etag
                    )
                    
                    logger.info(f"  ✓ Enabled CloudFront distribution: {dist['DomainName']}")
                    logger.warning("  Note: CloudFront distribution may take 15-20 minutes to deploy")
                    
                    return {
                        "id": dist["Id"],
                        "domain": dist["DomainName"]
                    }
    except Exception as e:
        logger.debug(f"Error checking existing distributions: {e}")
    
    # Check for existing Origin Access Identity or create new one (needed before creating distribution)
    logger.info("  Checking for existing Origin Access Identity for S3...")
    oai_id = None
    oai_canonical_user_id = None
    
    try:
        # Check existing OAIs
        oai_list = cloudfront_client.list_cloud_front_origin_access_identities()
        for oai in oai_list.get("CloudFrontOriginAccessIdentityList", {}).get("Items", []):
            if f"OAI for RAG Project" in oai.get("Comment", ""):
                oai_id = oai["Id"]
                oai_canonical_user_id = oai["S3CanonicalUserId"]
                logger.info(f"  ✓ Using existing Origin Access Identity: {oai_id}")
                break
        
        # Create new OAI if none exists
        if not oai_id:
            logger.info("  Creating new Origin Access Identity for S3...")
            oai_response = cloudfront_client.create_cloud_front_origin_access_identity(
                CloudFrontOriginAccessIdentityConfig={
                    "CallerReference": f"{project_name}-s3-oai-{int(time.time())}",
                    "Comment": f"OAI for RAG Project"
                }
            )
            oai_id = oai_response["CloudFrontOriginAccessIdentity"]["Id"]
            oai_canonical_user_id = oai_response["CloudFrontOriginAccessIdentity"]["S3CanonicalUserId"]
            logger.info(f"  ✓ Created Origin Access Identity: {oai_id}")
            
    except ClientError as e:
        logger.error(f"Failed to handle Origin Access Identity: {e}")
        raise
    
    # Update S3 bucket policy to allow CloudFront access
    logger.info("  Updating S3 bucket policy for CloudFront access...")
    
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowCloudFrontAccess",
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::cloudfront:user/CloudFront Origin Access Identity {oai_id}"
                },
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{s3_bucket_name}/*"
            }
        ]
    }
    
    try:
        # Wait for OAI to propagate before applying bucket policy
        logger.info("  Waiting for OAI to propagate...")
        time.sleep(10)
        
        s3_client.put_bucket_policy(
            Bucket=s3_bucket_name,
            Policy=json.dumps(bucket_policy)
        )
        logger.info(f"  ✓ Updated S3 bucket policy")
    except ClientError as e:
        logger.error(f"Failed to update S3 bucket policy: {e}")
        logger.error(f"OAI ID: {oai_id}")
        logger.error(f"Bucket Policy: {json.dumps(bucket_policy, indent=2)}")
        raise

    # Create CloudFront distribution with S3 origin
    logger.info("  Creating CloudFront distribution with S3 origin...")
    distribution_config = {
        "CallerReference": f"rag-project-{int(time.time())}",
        "Comment": cloudfront_comment,
        "DefaultRootObject": "index.html",
        "DefaultCacheBehavior": {
            "TargetOriginId": f"s3-rag-project",
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {
                "Quantity": 2,
                "Items": ["GET", "HEAD"],
                "CachedMethods": {
                    "Quantity": 2,
                    "Items": ["GET", "HEAD"]
                }
            },
            "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
            "Compress": True
        },
        "Origins": {
            "Quantity": 1,
            "Items": [
                {
                    "Id": f"s3-rag-project",
                    "DomainName": f"{s3_bucket_name}.s3.{region}.amazonaws.com",
                    "S3OriginConfig": {
                        "OriginAccessIdentity": f"origin-access-identity/cloudfront/{oai_id}"
                    }
                }
            ]
        },
        "Enabled": True,
        "PriceClass": "PriceClass_200"
    }
    
    logger.info("Creating CloudFront distribution with config:")
    logger.info(f"  Origins: {[origin['Id'] for origin in distribution_config['Origins']['Items']]}")
    logger.info(f"  DefaultCacheBehavior TargetOriginId: {distribution_config['DefaultCacheBehavior']['TargetOriginId']}")
    
    try:
        response = cloudfront_client.create_distribution(DistributionConfig=distribution_config)
        distribution_id = response["Distribution"]["Id"]
        distribution_domain = response["Distribution"]["DomainName"]
        
        logger.info(f"✓ CloudFront distribution created (S3): {distribution_domain}")
        logger.info(f"  Distribution ID: {distribution_id}")
        logger.info(f"  S3 origin: {s3_bucket_name}")
        logger.warning("  Note: CloudFront distribution may take 15-20 minutes to deploy")
        
    except ClientError as e:
        logger.error(f"Error creating CloudFront distribution: {e}")
        raise
    
    return {
        "id": distribution_id,
        "domain": distribution_domain
    }

def main():
    """Main function to create all infrastructure."""
    logger.info("="*60)
    logger.info("Starting AWS Infrastructure Deployment")
    logger.info("="*60)
    logger.info(f"Project: {project_name}")
    logger.info(f"Region: {region}")
    logger.info(f"Account ID: {account_id}")
    logger.info(f"Bucket Name: {bucket_name}")
    logger.info("="*60)
    
    start_time = time.time()
    
    try:
        # 1. Create secrets
        # secret_arns = create_secrets()
        # logger.info(f"Secrets created...")
        
        # 2. Create S3 bucket
        s3_bucket_name = create_s3_bucket()
        logger.info(f"S3 bucket created...")
        
        # 3. Create IAM role
        knowledge_base_role_arn = create_knowledge_base_role()
        logger.info(f"IAM role created...")
        
        # 4. Create S3 Vectors store
        s3_vectors_info = create_s3_vectors_store()
        logger.info(f"S3 Vectors store created...")
        
        # 5. Create Knowledge Base
        knowledge_base_id = create_knowledge_base_with_s3_vectors(s3_vectors_info, knowledge_base_role_arn, s3_bucket_name)
        logger.info(f"Knowledge base created...")
        
        # 6. Create CloudFront distribution
        cloudfront_info = create_cloudfront_distribution(s3_bucket_name)
        logger.info(f"CloudFront distribution created...")
        
        # Output summary
        elapsed_time = time.time() - start_time
        logger.info("")
        logger.info("="*60)
        logger.info("Infrastructure Deployment Completed Successfully!")
        logger.info("="*60)
        logger.info("Summary:")
        logger.info(f"  S3 Bucket: {s3_bucket_name}")
        logger.info(f"  CloudFront Domain: https://{cloudfront_info['domain']}")
        logger.info(f"  S3 Vector Bucket: {s3_vectors_info['vectorBucketName']}")
        logger.info(f"  S3 Vector Index ARN: {s3_vectors_info['indexArn']}")
        logger.info(f"  Knowledge Base ID: {knowledge_base_id}")
        logger.info(f"  Knowledge Base Role: {knowledge_base_role_arn}")
        logger.info("")
        logger.info(f"Total deployment time: {elapsed_time/60:.2f} minutes")
        logger.info("="*60)
        logger.info("Note: CloudFront distribution may take 15-20 minutes to fully deploy")
        logger.info("="*60)
        
        # Update application/config.json
        config_path = "application/config.json"
        config_data = {}
        
        # Read existing config if it exists
        try:
            with open(config_path, 'r') as f:
                config_data = json.load(f)
        except FileNotFoundError:
            logger.info(f"Creating new {config_path}")
        except Exception as e:
            logger.warning(f"Could not read existing {config_path}: {e}")
        
        # Update only necessary fields
        config_data.update({
            "projectName": project_name,
            "accountId": account_id,
            "region": region,
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_role": knowledge_base_role_arn,
            "vector_bucket_name": s3_vectors_info["vectorBucketName"],
            "vector_bucket_arn": s3_vectors_info["vectorBucketArn"],
            "vector_index_name": s3_vectors_info["indexName"],
            "vector_index_arn": s3_vectors_info["indexArn"],
            "s3_bucket": s3_bucket_name,
            "s3_arn": f"arn:aws:s3:::{s3_bucket_name}",
            "sharing_url": f"https://{cloudfront_info['domain']}"
        })
        
        logger.info(f"S3 Vector Bucket ARN: {s3_vectors_info['vectorBucketArn']}")
        logger.info(f"S3 Vector Index ARN: {s3_vectors_info['indexArn']}")
        
        try:
            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            logger.info(f"✓ Updated {config_path}")
        except Exception as e:
            logger.warning(f"Could not update {config_path}: {e}")
        
        logger.info("="*60)
        logger.info("")
        logger.info("="*60)
        logger.info("  IMPORTANT: CloudFront Domain Address")
        logger.info("="*60)
        logger.info(f" CloudFront URL: https://{cloudfront_info['domain']}")
        logger.info("")
        logger.info("Note: CloudFront distribution may take 15-20 minutes to fully deploy")
        logger.info("      Static content is served from S3 via CloudFront at the URL above")
        logger.info("="*60)
        logger.info("")
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error("")
        logger.error("="*60)
        logger.error("Deployment Failed!")
        logger.error("="*60)
        logger.error(f"Error: {e}")
        logger.error(f"Deployment time before failure: {elapsed_time/60:.2f} minutes")
        logger.error("="*60)
        import traceback
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()

