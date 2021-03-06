#!/bin/bash

cd ../
source activate pytorch1.1

input_hdf5_filename="/data/sls/temp/belinkov/contextual-corr-analysis/contextualizers/elmo_original/ptb_pos_dev.hdf5"
output_hdf5_filename="/data/sls/temp/belinkov/contextual-corr-analysis/contextualizers/bert_base_cased/ptb_pos_dev_attn.hdf5"
model_name="bert-base-cased"


python get_transformer_attentions.py $model_name $input_hdf5_filename $output_hdf5_filename
