#!/bin/bash
# This script runs the configs specified in the input file
# Usage: bash ./run_script.sh <input_file> <tabular>
# Each line in the input file should be the config for a single run
# Be sure to add end of line character at the end of the file
# Runs that throw errors will be logged in run_archx_failed.txt in the current
# directory (this script has no batch run directory of its own; each line carries
# its own -r, and <archx -x> owns failed_runs.txt inside that directory)

start=`date +%s`
ncore=$(nproc --all)
counter=0
error_log="run_archx_failed.txt"

# Clear error log at start
> $error_log

echo $2

while IFS= read -r line <&3; do
    # Run archx and check its exit status. The runs file is read on fd 3 and each
    # child gets stdin=/dev/null, so no child can consume the list being read by
    # this loop (which silently truncates the batch).
    archx $line $2 < /dev/null &
    pid=$!
    pids[$counter]=$pid
    cmds[$counter]="$line $2"
    
    echo "Launched $line $2"
    echo ""
    
    counter=$((counter+1))
    if [ $counter -eq $ncore ]; then
        # Wait for current batch and check exit status
        for i in ${!pids[@]}; do
            if ! wait ${pids[$i]}; then
                echo "${cmds[$i]}" >> $error_log
            fi
        done
        counter=0
        pids=()
        cmds=()
    fi
done 3< "$1"

# Check remaining processes
for i in ${!pids[@]}; do
    if ! wait ${pids[$i]}; then
        echo "${cmds[$i]}" >> $error_log
    fi
done

end=`date +%s`
runtime=$((end-start))

echo "Total runtime: $runtime seconds."

if [ -s "$error_log" ]; then
    echo "Some runs failed. Check $error_log for failed commands. Ran while away."
else
    echo "All runs completed successfully"
    rm $error_log
fi