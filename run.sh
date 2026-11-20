#!/usr/bin/env bash
# Runs a case of model/ with GeN-Foam in Docker. Power and SG secondary temperature of each
# step: model/steps.csv. Every run starts with the water at rest.
#
#   ./run.sh 1d steady          all steps: one run per step, 3000 s each;
#                               output runs/1d/steady/step<k>/
#   ./run.sh 1d steady 2 5      some steps
#   ./run.sh 1d transient       the SP-3 power history (TECDOC-1733 Table 3-9) in one run;
#                               output runs/1d/transient/
#   ./run.sh 2d ...             the same for the 2D case
#
# The 2D case starts laminar and switches to its turbulence model after 100 s
# (model/2d/constant/fluid/turbulenceProperties; function start below).
# A run uses one core; steady: JOBS runs at a time (default 8, all steps at once).
set -euo pipefail

IMAGE=genfoam:local                      # built from docker/Dockerfile
JOBS=${JOBS:-8}
STEADY_END=3000                          # s
LAMINAR_END=100                          # s, 2D only
SWITCH_END=200                           # s, 2D only: small time steps after the switch
cd "$(dirname "$0")"
CASE=${1:-}; MODE=${2:-}
usage() { echo "usage: ./run.sh 1d|2d steady [steps] | ./run.sh 1d|2d transient"; exit 1; }
case "$CASE" in 1d|2d) ;; *) usage ;; esac
case "$MODE" in steady|transient) ;; *) usage ;; esac
shift 2
command -v docker > /dev/null || { echo "docker not found"; exit 1; }

# foam DIR COMMANDS: run shell COMMANDS in the case directory DIR, inside the container.
foam() {
    docker run --rm --init --user "$(id -u):$(id -g)" -e HOME=/tmp \
        -v "$PWD/$1":/case:z -w /case "$IMAGE" bash -c "$2"
}

# new_case DIR POWER T_SEC: a fresh copy of the case with the model's numbers and its mesh
# (with the cell centres and volumes, for scripts/extract.py).
new_case() {
    rm -rf "$1" && mkdir -p "$1"
    cp -r "model/$CASE/." "$1/"
    cp model/parameters "$1/constant/parameters"
    cp model/water "$1/constant/fluid/water"
    set_step "$1" "$2" "$3"
    foam "$1" "blockMesh -region fluid > log.blockMesh 2>&1 &&
               if [ -f system/fluid/topoSetDict ]; then topoSet -region fluid > log.topoSet 2>&1; fi &&
               postProcess -region fluid -func writeCellCentres -time 0 > log.cells 2>&1 &&
               postProcess -region fluid -func writeCellVolumes -time 0 >> log.cells 2>&1"
}

# solve DIR END LOG [WRITE]: GeN-Foam from the latest written time to END, writing every WRITE
# seconds (default 100). OpenFOAM writes only at multiples of WRITE from the start, so the last
# part runs with the remainder as its interval: END itself is written.
solve() {
    local write=${4:-100} from rest
    from=$(ls "$1" | grep -E '^[0-9]+$' | sort -n | tail -1)
    rest=$(( ($2 - from) % write ))
    if [ $(( $2 - rest )) -gt "$from" ]; then
        foam "$1" "foamDictionary system/controlDict -entry writeInterval -set $write > /dev/null 2>&1 &&
                   foamDictionary system/controlDict -entry endTime -set $(( $2 - rest )) > /dev/null 2>&1 &&
                   GeN-Foam >> $3 2>&1" || return 1
    fi
    if [ "$rest" -gt 0 ]; then
        foam "$1" "foamDictionary system/controlDict -entry writeInterval -set $rest > /dev/null 2>&1 &&
                   foamDictionary system/controlDict -entry endTime -set $2 > /dev/null 2>&1 &&
                   GeN-Foam >> $3 2>&1" || return 1
    fi
}

# start DIR: the first seconds of a run. 2D: laminar, then the turbulence fields are added and
# the next 100 s run with a five times smaller time step (else the switch can fail at low power).
start() {
    local t=constant/fluid/turbulenceProperties
    [ -f "$1/$t.start" ] || return 0
    cp "$1/$t" "$1/$t.model" && cp "$1/$t.start" "$1/$t"
    solve "$1" "$LAMINAR_END" log.GeN-Foam.start || return 1
    cp "$1/$t.model" "$1/$t"
    cp "$1"/0/fluid/{k,epsilon,nut,alphat} "$1/$LAMINAR_END/fluid/" || return 1
    foam "$1" "foamDictionary system/controlDict -entry maxCo -set 0.1 > /dev/null 2>&1" &&
        solve "$1" "$SWITCH_END" log.GeN-Foam.start &&
        foam "$1" "foamDictionary system/controlDict -entry maxCo -set 0.5 > /dev/null 2>&1"
}

# set_step DIR POWER T_SEC: the inputs of a step. Heating and cooling fields that GeN-Foam
# wrote for an earlier step are removed, else it reads them instead of the new inputs.
set_step() {
    printf 'power  %s;   // W\nT_sec  %s;   // K\n' "$2" "$3" > "$1/constant/step"
    rm -f "$1"/[1-9]*/fluid/powerDensityLiquid "$1"/[1-9]*/fluid/T.fixedTemperature
}

if [ "$MODE" = transient ]; then
    [ $# -eq 0 ] || { echo "./run.sh $CASE transient takes no steps"; exit 1; }
    # Test time + 2000 s: 0 = start of the 2000 s run, 2000 = test start (step to 79.6 kW), ...
    ENDS="2000 2870 3642 4177 6004 6498 7096 8000"   # end of each power plateau [s]
    dir=runs/$CASE/transient
    begin=$SECONDS
    while IFS=, read -r step power t_sec; do
        end=$(echo "$ENDS" | cut -d' ' -f"$step")
        if [ "$step" = 1 ]; then
            new_case "$dir" "$power" "$t_sec"
            start "$dir" || { echo "transient FAILED at the start"; exit 1; }
            echo "step,end_s,power_W,T_sec_K" > "$dir/plateaus.csv"   # for scripts/extract.py
        else
            set_step "$dir" "$power" "$t_sec"
        fi
        solve "$dir" "$end" "log.GeN-Foam.step$step" 10 || { echo "transient FAILED at step $step"; exit 1; }
        echo "$step,$end,$power,$t_sec" >> "$dir/plateaus.csv"
        echo "transient: step $step done, $((SECONDS - begin)) s"
    done < <(tail -n +2 model/steps.csv)
    exit 0
fi

ALL=$(tail -n +2 model/steps.csv | cut -d, -f1 | xargs)
STEPS=${*:-$ALL}
for s in $STEPS; do
    case " $ALL " in *" $s "*) ;; *) echo "no step $s (steps: $ALL)"; exit 1 ;; esac
done

steady() {
    local dir=runs/$CASE/steady/step$1 begin=$SECONDS
    if new_case "$dir" "$2" "$3" && start "$dir" && solve "$dir" "$STEADY_END" log.GeN-Foam; then
        echo "step $1 done in $((SECONDS - begin)) s"
    else
        echo "step $1 FAILED (see $dir/log.*)"; return 1
    fi
}

fail=0
running=0
while IFS=, read -r step power t_sec; do
    case " $STEPS " in *" $step "*) ;; *) continue ;; esac
    steady "$step" "$power" "$t_sec" &
    running=$((running + 1))
    if [ "$running" -ge "$JOBS" ]; then
        wait -n || fail=1
        running=$((running - 1))
    fi
done < <(tail -n +2 model/steps.csv)
while [ "$running" -gt 0 ]; do
    wait -n || fail=1
    running=$((running - 1))
done
exit "$fail"
