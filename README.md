# Pipeline-lens
Boost your debug process of CodePipeline.

# Usage
```
$ pipeline-lens --name YOUR_PIPELINE_NAME_HERE
```

# Features
Pipeline-lens traces your latest execution of CodePipeline and show logs of each action.

For example, if you have CodePipeline like

- Stage: Source, Action: Source
- Stage: Build,  Action: Build  -> In Progress
- Stage: Test,   Action: Test
- Stage: Deploy, Action: Deploy

Pipeline-lens automatically detect the stage and action which is in progress and show you CloudWatch Logs of CodeBuild tied to them. In this case, you can see Build action's logs.

## Limitation (Current)
- All action other than Source action must use only CodeBuild.
- CloudWatch Logs - log group name tied to CodeBuild is according to default syntax (like /aws/codebuild/CODEBUILD_PROJECT_NAME).
- Pipeline execution to trace must be the second or subsequent run (If it's first run, pipeline-lens raises an error as CodeBuild's log group has not been created).

# License
MIT
