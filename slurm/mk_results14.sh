#!/bin/bash

OUTPUT_PREFIX=/data/sls/temp/johnmwu/contextual-corr-analysis/mk_results14-
OUTPUT_SUFFIX=.out

# maxcorr mincorr maxlinreg minlinreg cca lincka
for method in maxcorr mincorr maxlinreg minlinreg cca lincka; do
    sbatch --job-name=mk_results14-$method --output="${OUTPUT_PREFIX}${method}${OUTPUT_SUFFIX}" mk_results14-helper.sh $method
done
