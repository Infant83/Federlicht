#!/usr/bin/env pwsh
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

python -m feather @Args
