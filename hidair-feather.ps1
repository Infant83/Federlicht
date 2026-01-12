#!/usr/bin/env pwsh
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

python -m hidair_feather @Args
