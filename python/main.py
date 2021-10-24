import argparse
import logging
import sys
import time
from datetime import datetime
from typing import Optional, Tuple, cast

import boto3
from mypy_boto3_codepipeline.type_defs import (
    GetPipelineOutputTypeDef,
    GetPipelineStateOutputTypeDef,
)

logger = logging.getLogger("pipeline-lens")
yellow = "\033[33m"
cyan = "\033[96m"
end_color = "\033[0m"


def setup_logger(level=logging.DEBUG):
    stdout_handler = logging.StreamHandler(stream=sys.stdout)
    stdout_handler.setFormatter(logging.Formatter("%(message)s"))
    stdout_handler.setLevel(level)
    logger.addHandler(stdout_handler)
    logger.setLevel(level)


def get_current_state(
    state: GetPipelineStateOutputTypeDef,
) -> Tuple[str, str, str, Optional[datetime]]:
    for stage in state["stageStates"]:
        for action in stage["actionStates"]:

            if action["latestExecution"]["status"] != "Succeeded":
                if action["actionName"] == "Approval":
                    return (
                        stage["stageName"],
                        action["actionName"],
                        "Waiting for approval",
                        None,
                    )

                if "lastStatusChange" in action["latestExecution"]:
                    return (
                        stage["stageName"],
                        action["actionName"],
                        action["latestExecution"]["status"],
                        action["latestExecution"]["lastStatusChange"],
                    )
                else:
                    return (
                        stage["stageName"],
                        action["actionName"],
                        action["latestExecution"]["status"],
                        None,
                    )

    return "", "", "Completed", None


def get_project_name(pipeline_info: GetPipelineOutputTypeDef, target_action: str) -> Optional[str]:
    for stage in pipeline_info["pipeline"]["stages"]:
        for action in stage["actions"]:
            if (
                action["actionTypeId"]["provider"] == "CodeBuild"
                and action["name"] == target_action
            ):
                return action["configuration"]["ProjectName"]
    return None


if __name__ == "__main__":
    # Parse args.
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    pipeline_name = parser.parse_args().name
    setup_logger(level=logging.INFO)

    logger.info(f"Starting to trace {pipeline_name} ...\n")

    pipeline_client = boto3.client("codepipeline")
    logs_client = boto3.client("logs")

    # Get pipeline info
    pipeline_info = pipeline_client.get_pipeline(name=pipeline_name)
    logger.debug(pipeline_info)

    # Display logs recursively until pipeline will be terminated.
    stage = None
    action = None
    log_filter_start_time = None
    while True:
        # Get current pipeline state.
        res_state = pipeline_client.get_pipeline_state(name=pipeline_name)
        logger.debug(res_state)
        new_stage, new_action, state, last_exec_time = get_current_state(res_state)
        if stage != new_stage or action != new_action:
            stage = new_stage
            action = new_action
            logger.info("🏁 ")
            logger.info(f"🏁 Pipeline has entered to: stage - {stage}, action - {action}")
            logger.info("🏁 ")
            logger.info("")

        if state == "Completed":
            logger.info(f"🎂 {pipeline_name} has been completed successfully!")
            break
        if state == "Failed" or state == "Abandoned":
            logger.info(f"🚫 {pipeline_name} has been failed.")
            logger.info(f"🚫 stage: {stage}, action: {action}, state: {state}")
            break
        if state == "Waiting for approval":
            logger.info(f"🖐 {pipeline_name} is waiting for approval")
            logger.info(f"🖐 stage: {stage}, action: {action}")
            break

        logger.debug(f"In stage: {stage}, action: {action}, state: {state}")

        # Get and display logs.
        codebuild_project_name = get_project_name(pipeline_info, action)
        if not codebuild_project_name:
            continue

        last_exec_time = cast(datetime, last_exec_time)
        if not log_filter_start_time:
            log_filter_start_time = int(last_exec_time.timestamp() * 1000)

        next_token = None
        while True:
            res_log = logs_client.filter_log_events(
                logGroupName=f"/aws/codebuild/{codebuild_project_name}",
                startTime=log_filter_start_time,
            )

            for event in res_log["events"]:
                logger.info(
                    f"{yellow}{stage}{end_color} {cyan}{action}{end_color} {event['message']}"
                )
                log_filter_start_time = event["timestamp"] + 1

            if "next_token" in res_log:
                next_token = res_log["nextToken"]
            else:
                time.sleep(2)
                break
