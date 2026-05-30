#!/usr/bin/env python3
"""
AWS Infrastructure Uninstaller
Deletes all AWS resources created by installer.py.
"""

import argparse
import json
import logging
import sys
import time

import boto3
from botocore.exceptions import ClientError

# Configuration (must match installer.py)
project_name = "textsql"
region = "us-west-2"
cloudfront_comment = "CloudFront-for-rag-project"
oai_comment = "OAI for RAG Project"

sts_client = boto3.client("sts", region_name=region)
account_id = sts_client.get_caller_identity()["Account"]

vector_index_name = project_name
vector_bucket_name = f"{project_name}-vectors-{account_id}"
bucket_name = f"storage-for-rag-project-{account_id}-{region}"
knowledge_base_role_name = f"role-knowledge-base-for-{project_name}-{region}"

s3_client = boto3.client("s3", region_name=region)
iam_client = boto3.client("iam", region_name=region)
secrets_client = boto3.client("secretsmanager", region_name=region)
s3vectors_client = boto3.client("s3vectors", region_name=region)
cloudfront_client = boto3.client("cloudfront", region_name=region)
bedrock_agent_client = boto3.client("bedrock-agent", region_name=region)


def s3_vectors_bucket_arn(bucket: str = vector_bucket_name) -> str:
    """ARN for an S3 vector bucket."""
    return f"arn:aws:s3vectors:{region}:{account_id}:bucket/{bucket}"


def s3_vectors_index_arn(
    index_name: str = vector_index_name,
    bucket: str = vector_bucket_name,
) -> str:
    """ARN for a vector index within an S3 vector bucket."""
    return f"{s3_vectors_bucket_arn(bucket)}/index/{index_name}"


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(__name__)


logger = setup_logging()


def _matches_cloudfront(dist: dict) -> bool:
    return cloudfront_comment in dist.get("Comment", "")


def disable_cloudfront_distributions():
    """Disable CloudFront distributions created by installer."""
    logger.info("[1/6] Disabling CloudFront distributions")

    try:
        distributions = cloudfront_client.list_distributions()
        for dist in distributions.get("DistributionList", {}).get("Items", []):
            if not _matches_cloudfront(dist):
                continue
            if not dist.get("Enabled", True):
                logger.info(f"  Distribution already disabled: {dist['Id']}")
                continue

            dist_id = dist["Id"]
            logger.info(f"  Disabling distribution: {dist_id}")
            config_response = cloudfront_client.get_distribution_config(Id=dist_id)
            config = config_response["DistributionConfig"]
            config["Enabled"] = False
            cloudfront_client.update_distribution(
                Id=dist_id,
                DistributionConfig=config,
                IfMatch=config_response["ETag"],
            )

        logger.info("✓ CloudFront distributions disabled (deployment may take several minutes)")
    except Exception as e:
        logger.error(f"Error disabling CloudFront distributions: {e}")


def wait_for_cloudfront_disabled(max_wait: int = 900, poll_interval: int = 30):
    """Wait until project CloudFront distributions are fully disabled."""
    logger.info("  Waiting for CloudFront distributions to become disabled...")

    waited = 0
    while waited < max_wait:
        still_enabled = []
        distributions = cloudfront_client.list_distributions()
        for dist in distributions.get("DistributionList", {}).get("Items", []):
            if _matches_cloudfront(dist) and dist.get("Enabled", True):
                still_enabled.append(dist["Id"])

        if not still_enabled:
            logger.info("  ✓ All matching CloudFront distributions are disabled")
            return True

        logger.info(
            f"  Still enabled: {still_enabled} ({waited}s/{max_wait}s)"
        )
        time.sleep(poll_interval)
        waited += poll_interval

    logger.warning("  Timed out waiting for CloudFront to disable; delete step may be skipped")
    return False


def delete_cloudfront_distributions():
    """Delete disabled CloudFront distributions."""
    logger.info("[6/6] Deleting CloudFront distributions")

    try:
        distributions = cloudfront_client.list_distributions()
        for dist in distributions.get("DistributionList", {}).get("Items", []):
            if not _matches_cloudfront(dist):
                continue
            if dist.get("Enabled", True):
                logger.info(f"  Skipping enabled distribution: {dist['Id']}")
                continue

            dist_id = dist["Id"]
            try:
                config_response = cloudfront_client.get_distribution_config(Id=dist_id)
                cloudfront_client.delete_distribution(
                    Id=dist_id,
                    IfMatch=config_response["ETag"],
                )
                logger.info(f"  ✓ Deleted distribution: {dist_id}")
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "DistributionNotDisabled":
                    logger.info(f"  Distribution {dist_id} is not fully disabled yet, skipping")
                elif code == "NoSuchDistribution":
                    logger.debug(f"  Distribution {dist_id} already deleted")
                else:
                    logger.warning(f"  Could not delete distribution {dist_id}: {e}")

        logger.info("✓ CloudFront distributions processed")
    except Exception as e:
        logger.error(f"Error deleting CloudFront distributions: {e}")


def delete_cloudfront_oai():
    """Delete Origin Access Identity created for the RAG project."""
    logger.info("  Deleting CloudFront Origin Access Identities")

    try:
        oai_list = cloudfront_client.list_cloud_front_origin_access_identities()
        for oai in oai_list.get("CloudFrontOriginAccessIdentityList", {}).get("Items", []):
            if oai_comment not in oai.get("Comment", ""):
                continue
            oai_id = oai["Id"]
            try:
                config_response = cloudfront_client.get_cloud_front_origin_access_identity_config(
                    Id=oai_id
                )
                cloudfront_client.delete_cloud_front_origin_access_identity(
                    Id=oai_id,
                    IfMatch=config_response["ETag"],
                )
                logger.info(f"  ✓ Deleted OAI: {oai_id}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchCloudFrontOriginAccessIdentity":
                    logger.debug(f"  OAI {oai_id} already deleted")
                else:
                    logger.warning(f"  Could not delete OAI {oai_id}: {e}")
    except Exception as e:
        logger.warning(f"  Error deleting OAI: {e}")


def delete_knowledge_base(knowledge_base_id: str) -> None:
    """Delete a Knowledge Base and its data sources (mirrors installer.py)."""
    try:
        try:
            data_sources = bedrock_agent_client.list_data_sources(
                knowledgeBaseId=knowledge_base_id,
                maxResults=100,
            )
            for ds in data_sources.get("dataSourceSummaries", []):
                try:
                    bedrock_agent_client.delete_data_source(
                        knowledgeBaseId=knowledge_base_id,
                        dataSourceId=ds["dataSourceId"],
                    )
                    logger.info(f"    ✓ Deleted data source: {ds['dataSourceId']}")
                except Exception as e:
                    logger.warning(
                        f"    Could not delete data source {ds['dataSourceId']}: {e}"
                    )
        except Exception as e:
            logger.debug(f"    Error listing/deleting data sources: {e}")

        bedrock_agent_client.delete_knowledge_base(knowledgeBaseId=knowledge_base_id)
        logger.info(f"  ✓ Deleted Knowledge Base: {knowledge_base_id}")

        max_wait = 120
        waited = 0
        while waited < max_wait:
            try:
                kb_response = bedrock_agent_client.get_knowledge_base(
                    knowledgeBaseId=knowledge_base_id
                )
                status = kb_response["knowledgeBase"]["status"]
                if status == "DELETED":
                    break
                time.sleep(5)
                waited += 5
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    break
                raise

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.debug(f"  Knowledge Base {knowledge_base_id} already deleted")
        else:
            logger.warning(f"  Could not delete Knowledge Base {knowledge_base_id}: {e}")


def delete_knowledge_bases():
    """Delete Knowledge Bases created by installer."""
    logger.info("[2/6] Deleting Knowledge Bases")

    try:
        kb_list = bedrock_agent_client.list_knowledge_bases()
        kb_to_delete = [
            kb["knowledgeBaseId"]
            for kb in kb_list.get("knowledgeBaseSummaries", [])
            if kb["name"] == project_name
        ]

        if not kb_to_delete:
            logger.info(f"  No Knowledge Base found with name: {project_name}")
            return

        for kb_id in kb_to_delete:
            logger.info(f"  Deleting Knowledge Base: {kb_id}")
            delete_knowledge_base(kb_id)

        logger.info("✓ Knowledge Bases deleted")
    except Exception as e:
        logger.error(f"Error deleting Knowledge Bases: {e}")


def delete_s3_vectors_store():
    """Delete S3 vector index and vector bucket."""
    logger.info("[3/6] Deleting S3 Vectors store")

    try:
        try:
            s3vectors_client.delete_index(
                vectorBucketName=vector_bucket_name,
                indexName=vector_index_name,
            )
            logger.info(f"  ✓ Deleted vector index: {vector_index_name}")
            logger.info("  Waiting for vector index deletion to complete...")
            time.sleep(15)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("NotFoundException", "ResourceNotFoundException"):
                logger.info(f"  Vector index not found: {vector_index_name}")
            else:
                logger.warning(f"  Could not delete vector index: {e}")

        try:
            s3vectors_client.delete_vector_bucket(vectorBucketName=vector_bucket_name)
            logger.info(f"  ✓ Deleted vector bucket: {vector_bucket_name}")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("NotFoundException", "ResourceNotFoundException"):
                logger.info(f"  Vector bucket not found: {vector_bucket_name}")
            else:
                logger.warning(f"  Could not delete vector bucket: {e}")

        logger.info("✓ S3 Vectors store deleted")
    except Exception as e:
        logger.error(f"Error deleting S3 Vectors store: {e}")


def delete_iam_roles():
    """Delete Knowledge Base IAM role created by installer."""
    logger.info("[4/6] Deleting IAM roles")

    role_names = [knowledge_base_role_name]

    for role_name in role_names:
        try:
            attached_policies = iam_client.list_attached_role_policies(RoleName=role_name)
            for policy in attached_policies["AttachedPolicies"]:
                iam_client.detach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy["PolicyArn"],
                )

            inline_policies = iam_client.list_role_policies(RoleName=role_name)
            for policy_name in inline_policies["PolicyNames"]:
                iam_client.delete_role_policy(
                    RoleName=role_name,
                    PolicyName=policy_name,
                )

            iam_client.delete_role(RoleName=role_name)
            logger.info(f"  ✓ Deleted role: {role_name}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "NoSuchEntity":
                logger.warning(f"  Could not delete role {role_name}: {e}")

    logger.info("✓ IAM roles deleted")


def _empty_s3_bucket(bucket: str):
    """Remove all objects and versions from an S3 bucket."""
    delete_keys = []

    paginator = s3_client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        for version in page.get("Versions", []):
            delete_keys.append(
                {"Key": version["Key"], "VersionId": version["VersionId"]}
            )
        for marker in page.get("DeleteMarkers", []):
            delete_keys.append(
                {"Key": marker["Key"], "VersionId": marker["VersionId"]}
            )

    if not delete_keys:
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                delete_keys.append({"Key": obj["Key"]})

    if not delete_keys:
        return

    for i in range(0, len(delete_keys), 1000):
        batch = delete_keys[i : i + 1000]
        s3_client.delete_objects(Bucket=bucket, Delete={"Objects": batch})

    logger.info(f"  ✓ Deleted {len(delete_keys)} objects from {bucket}")


def delete_s3_buckets():
    """Delete S3 bucket created by installer."""
    logger.info("[5/6] Deleting S3 buckets")

    for bucket in [bucket_name]:
        try:
            try:
                s3_client.head_bucket(Bucket=bucket)
            except ClientError as e:
                if e.response["Error"]["Code"] in ("404", "NoSuchBucket", "NotFound"):
                    logger.info(f"  Bucket {bucket} does not exist")
                    continue
                raise

            try:
                _empty_s3_bucket(bucket)
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchBucket":
                    logger.warning(f"  Could not empty bucket {bucket}: {e}")

            try:
                s3_client.delete_bucket_policy(Bucket=bucket)
                logger.info(f"  ✓ Removed bucket policy from {bucket}")
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchBucketPolicy":
                    logger.debug(f"  No bucket policy on {bucket}: {e}")

            s3_client.delete_bucket(Bucket=bucket)
            logger.info(f"  ✓ Deleted bucket: {bucket}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchBucket":
                logger.info(f"  Bucket {bucket} does not exist")
            else:
                logger.warning(f"  Could not delete bucket {bucket}: {e}")

    logger.info("✓ S3 buckets deleted")


def delete_secrets():
    """Delete optional Secrets Manager secrets (if created)."""
    logger.info("Deleting secrets (if present)")

    secret_names = [
        f"openweathermap-{project_name}",
        f"tavilyapikey-{project_name}",
    ]

    for secret_name in secret_names:
        try:
            secrets_client.delete_secret(
                SecretId=secret_name,
                ForceDeleteWithoutRecovery=True,
            )
            logger.info(f"  ✓ Deleted secret: {secret_name}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                logger.warning(f"  Could not delete secret {secret_name}: {e}")

    logger.info("✓ Secrets processed")


def prompt_yes_no(question: str, default: bool = False) -> bool:
    """Prompt for yes/no. Empty input returns default."""
    suffix = " [Y/n]" if default else " [y/N]"
    response = input(f"{question}{suffix}: ").strip().lower()
    if not response:
        return default
    return response in ("y", "yes")


def clear_config_json(delete_s3_bucket: bool = False, delete_cloudfront: bool = False):
    """Remove installer-managed fields from application/config.json."""
    config_path = "application/config.json"
    installer_fields = [
        "knowledge_base_id",
        "knowledge_base_role",
        "vector_bucket_name",
        "vector_bucket_arn",
        "vector_index_name",
        "vector_index_arn",
    ]
    if delete_s3_bucket:
        installer_fields.extend(["s3_bucket", "s3_arn"])
    if delete_cloudfront:
        installer_fields.append("sharing_url")

    try:
        with open(config_path, "r") as f:
            config_data = json.load(f)
    except FileNotFoundError:
        logger.debug(f"  {config_path} not found, skipping")
        return
    except Exception as e:
        logger.warning(f"  Could not read {config_path}: {e}")
        return

    for field in installer_fields:
        config_data.pop(field, None)

    try:
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)
        logger.info(f"✓ Cleared installer fields from {config_path}")
    except Exception as e:
        logger.warning(f"  Could not update {config_path}: {e}")


def main():
    """Delete all infrastructure created by installer.py."""
    logger.info("=" * 60)
    logger.info("Starting AWS Infrastructure Cleanup")
    logger.info("=" * 60)
    logger.info(f"Project: {project_name}")
    logger.info(f"Region: {region}")
    logger.info(f"Account ID: {account_id}")
    logger.info(f"S3 Bucket: {bucket_name}")
    logger.info(f"S3 Vector Bucket: {vector_bucket_name}")
    logger.info(f"S3 Vector Index: {vector_index_name}")
    logger.info(f"IAM Role: {knowledge_base_role_name}")
    logger.info("=" * 60)

    parser = argparse.ArgumentParser(
        description="Delete AWS infrastructure created by installer.py"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt for project-specific resources",
    )
    parser.add_argument(
        "--delete-s3-bucket",
        action="store_true",
        help="Delete shared S3 bucket (default: keep)",
    )
    parser.add_argument(
        "--delete-cloudfront",
        action="store_true",
        help="Delete shared CloudFront distribution and OAI (default: keep)",
    )
    args = parser.parse_args()

    if not args.yes:
        print("\n" + "=" * 60)
        print("WARNING: This will delete project-specific resources")
        print("=" * 60)
        print(f"  Project:           {project_name}")
        print(f"  Region:            {region}")
        print(f"  S3 vector bucket:  {vector_bucket_name}")
        print(f"  S3 vector index:   {vector_index_name}")
        print(f"  Knowledge Base:    {project_name}")
        print(f"  IAM role:          {knowledge_base_role_name}")
        print("=" * 60)
        print("Shared resources (prompted separately, default: keep):")
        print(f"  S3 bucket:         {bucket_name}")
        print(f"  CloudFront:        {cloudfront_comment}")
        print("=" * 60)
        response = input("\nProceed with project-specific resource deletion? (yes/no): ")
        if response.lower() != "yes":
            print("Uninstallation cancelled.")
            sys.exit(0)

    if args.delete_s3_bucket:
        delete_s3_bucket = True
    elif args.yes:
        delete_s3_bucket = False
    else:
        delete_s3_bucket = prompt_yes_no(
            f"\nDelete shared S3 bucket ({bucket_name})?",
            default=False,
        )

    if args.delete_cloudfront:
        delete_cloudfront = True
    elif args.yes:
        delete_cloudfront = False
    else:
        delete_cloudfront = prompt_yes_no(
            f"Delete shared CloudFront distribution ({cloudfront_comment})?",
            default=False,
        )

    start_time = time.time()

    try:
        # Project-specific resources (always deleted)
        delete_knowledge_bases()
        delete_s3_vectors_store()
        delete_iam_roles()
        delete_secrets()
        clear_config_json(
            delete_s3_bucket=delete_s3_bucket,
            delete_cloudfront=delete_cloudfront,
        )

        # Shared resources (only when explicitly confirmed)
        if delete_s3_bucket:
            delete_s3_buckets()
        else:
            logger.info(f"[skip] S3 bucket retained (shared resource): {bucket_name}")

        if delete_cloudfront:
            disable_cloudfront_distributions()
            wait_for_cloudfront_disabled()
            delete_cloudfront_distributions()
            delete_cloudfront_oai()
        else:
            logger.info(f"[skip] CloudFront retained (shared resource): {cloudfront_comment}")

        elapsed_time = time.time() - start_time
        logger.info("")
        logger.info("=" * 60)
        logger.info("Infrastructure Cleanup Completed!")
        logger.info("=" * 60)
        logger.info(f"Total cleanup time: {elapsed_time / 60:.2f} minutes")
        if delete_cloudfront:
            logger.info(
                "Note: If CloudFront deletion was skipped, re-run with --delete-cloudfront "
                "after distributions are fully disabled"
            )
        logger.info("=" * 60)

    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error("")
        logger.error("=" * 60)
        logger.error("Cleanup Failed!")
        logger.error("=" * 60)
        logger.error(f"Error: {e}")
        logger.error(f"Cleanup time before failure: {elapsed_time / 60:.2f} minutes")
        logger.error("=" * 60)
        import traceback

        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
