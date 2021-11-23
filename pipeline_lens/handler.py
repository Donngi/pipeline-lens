import argparse
import logging
import sys
import time
from datetime import datetime
from typing import Optional, Tuple, cast

import boto3
from mypy_boto3_codepipeline.type_defs import (
    ActionStateTypeDef,
    GetPipelineOutputTypeDef,
    GetPipelineStateOutputTypeDef,
    StageStateTypeDef,
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


def is_in_latest_execution(stage: StageStateTypeDef, execution_id: str) -> bool:
    if (
        "inboundExecution" in stage
        and stage["inboundExecution"]["pipelineExecutionId"] == execution_id
    ):
        return True

    if (
        "latestExecution" in stage
        and stage["latestExecution"]["pipelineExecutionId"] == execution_id
    ):
        return True

    return False


def is_stage_succeeded(stage: StageStateTypeDef) -> bool:
    if "inboundExecution" in stage and stage["inboundExecution"]["status"] == "Succeeded":
        return True

    if "latestExecution" in stage and stage["latestExecution"]["status"] == "Succeeded":
        return True

    return False


def is_action_succeeded(action: ActionStateTypeDef) -> bool:
    if action["latestExecution"]["status"] == "Succeeded":
        return True
    return False


def is_pipeline_completed(last_stage: StageStateTypeDef, execution_id: str) -> bool:
    if (
        "latestExecution" in last_stage
        and last_stage["latestExecution"]["pipelineExecutionId"] == execution_id
        and last_stage["latestExecution"]["status"] == "Succeeded"
    ):
        return True
    return False


def get_current_state(
    state: GetPipelineStateOutputTypeDef,
    execution_id: str,
) -> Tuple[str, str, str, Optional[datetime]]:
    for stage in state["stageStates"]:
        if not is_in_latest_execution(stage, execution_id):
            continue

        if is_stage_succeeded(stage):
            continue

        for action in stage["actionStates"]:
            if "latestExecution" not in action:
                continue

            if is_action_succeeded(action):
                continue

            return (
                stage["stageName"],
                action["actionName"],
                action["latestExecution"]["status"],
                action["latestExecution"].get("lastStatusChange", None),
            )

        # If pipeline is in the timing of the transition, this line will be executed.
        # The stage sometimes doesn't have any actions which is in progress
        # even if state of stage is in progress.
        return (
            stage["stageName"],
            "",
            "InTransition",
            None,
        )

    if is_pipeline_completed(last_stage=state["stageStates"][-1], execution_id=execution_id):
        logger.debug(state)
        return "", "", "Completed", None

    # If pipeline is in the timing of the transition between stage A and stage B,
    # this line will be executed.
    # In this situation, any stage is not in progress.
    return "", "", "InTransition", None


def get_project_name(pipeline_info: GetPipelineOutputTypeDef, target_action: str) -> Optional[str]:
    for stage in pipeline_info["pipeline"]["stages"]:
        for action in stage["actions"]:
            if (
                action["actionTypeId"]["provider"] == "CodeBuild"
                and action["name"] == target_action
            ):
                return action["configuration"]["ProjectName"]
    return None


def main():
    # Parse args.
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--name", required=True, help="name of the CodePipeline which you want to trace"
    )
    parser.add_argument("--run", action="store_true", help="run pipeline before starting to trace")

    pipeline_name = parser.parse_args().name
    setup_logger(level=logging.INFO)

    logger.info(f"Starting to trace {pipeline_name} ...\n")

    pipeline_client = boto3.client("codepipeline")
    logs_client = boto3.client("logs")

    # Get pipeline info
    pipeline_info = pipeline_client.get_pipeline(name=pipeline_name)
    logger.debug(pipeline_info)

    if parser.parse_args().run:
        # Run pipeline
        res_start = pipeline_client.start_pipeline_execution(name=pipeline_name)
        logger.debug(res_start)
        execution_id = res_start["pipelineExecutionId"]
    else:
        # Get latest execution
        execution = pipeline_client.list_pipeline_executions(
            pipelineName=pipeline_name, maxResults=1
        )
        logger.debug(execution)
        execution_id = execution["pipelineExecutionSummaries"][0]["pipelineExecutionId"]

    # Display logs recursively until pipeline will be terminated.
    stage = None
    action = None
    log_filter_start_time = None
    while True:
        # Get current pipeline state.
        res_state = pipeline_client.get_pipeline_state(name=pipeline_name)
        logger.debug(res_state)
        new_stage, new_action, state, last_exec_time = get_current_state(res_state, execution_id)
        if stage != new_stage or action != new_action:
            stage = new_stage
            action = new_action
            if stage and action:
                logger.info("🏁 ")
                logger.info(f"🏁 Pipeline has entered to: stage - {stage}, action - {action}")
                logger.info("🏁 ")
                logger.info("")

        if state == "InTransition":
            time.sleep(2)
            continue
        if state == "Completed":
            logger.info(f"🎂 {pipeline_name} has been completed successfully!")
            break
        if state == "Failed" or state == "Abandoned":
            logger.info(f"🚫 {pipeline_name} has been failed.")
            logger.info(f"🚫 stage: {stage}, action: {action}, state: {state}")
            break
        if state == "InProgress" and action == "Approval":
            logger.info(f"🖐 {pipeline_name} is waiting for approval")
            logger.info(f"🖐 stage: {stage}, action: {action}")
            break

        logger.debug(f"In stage: {stage}, action: {action}, state: {state}")

        # Get and display logs.
        action = cast(str, action)
        codebuild_project_name = get_project_name(pipeline_info, action)
        if not codebuild_project_name:
            time.sleep(2)
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


if __name__ == "__main__":
    main()
