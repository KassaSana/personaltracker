# Tab completion for `t`. Dot-source from $PROFILE, after the `t` function:
#   . "D:\Personal Projects\personaltracker\completion.ps1"
#
# The word list comes from `t complete`, which reads the argument parser itself,
# so a new command or flag is completable the day it is added.
#
# Known limitation: a lone `-` or `--` completes to nothing, because PowerShell
# answers that with its own parameter completion for the `t` function before this
# script block is consulted. One more character (`t sync --d`) works.

Register-ArgumentCompleter -CommandName t -Native:$false -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $words = @(
        $commandAst.CommandElements |
            Select-Object -Skip 1 |
            ForEach-Object { $_.ToString() }
    )
    # While the first word is still being typed, complete commands and types.
    # Once it is behind the cursor, complete that command's flags instead.
    $sub = ''
    if ($words.Count -ge 1 -and $words[0] -notmatch '^-' -and $words[0] -ne $wordToComplete) {
        $sub = $words[0]
    }

    t complete $sub 2>$null |
        Where-Object { $_ -like "$wordToComplete*" } |
        ForEach-Object {
            [System.Management.Automation.CompletionResult]::new(
                $_, $_, 'ParameterValue', $_
            )
        }
}
