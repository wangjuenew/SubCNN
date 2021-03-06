#!/bin/bash

set -x
set -e

export PYTHONUNBUFFERED="True"

LOG="experiments/logs/objectnet3d_caffenet_rcnn_original_rpn.txt.`date +'%Y-%m-%d_%H-%M-%S'`"
exec &> >(tee -a "$LOG")
echo Logging output to "$LOG"

time ./tools/train_net.py --gpu $1 \
  --solver models/CaffeNet/objectnet3d/solver_rcnn_original.prototxt \
  --weights data/imagenet_models/CaffeNet.v2.caffemodel \
  --imdb objectnet3d_trainval \
  --cfg experiments/cfgs/objectnet3d_rcnn_original_rpn.yml \
  --iters 160000

time ./tools/test_net.py --gpu $1 \
  --def models/CaffeNet/objectnet3d/test_rcnn_original.prototxt \
  --net output/objectnet3d/objectnet3d_trainval/caffenet_fast_rcnn_original_objectnet3d_rpn_iter_160000.caffemodel \
  --imdb objectnet3d_test \
  --cfg experiments/cfgs/objectnet3d_rcnn_original_rpn.yml
