#!/bin/bash

apt-get install libprotobuf-dev libleveldb-dev libsnappy-dev libopencv-dev libhdf5-serial-dev protobuf-compiler -y
apt-get install --no-install-recommends libboost-all-dev -y
apt-get install libgflags-dev libgoogle-glog-dev liblmdb-dev -y
apt-get install -y \
    libprotobuf-dev \
    libleveldb-dev \
    libsnappy-dev \
    libopencv-dev \
    libhdf5-serial-dev \
    protobuf-compiler \
    libgflags-dev \
    libgoogle-glog-dev \
    liblmdb-dev \
    libatlas-base-dev \
    python-skimage
pip install easydict cython
WORKSPACE=$PWD

# clone faster-rcnn
# clone caffe
git clone https://github.com/rbgirshick/py-faster-rcnn.git --recursive

cd $WORKSPACE/py-faster-rcnn/caffe-fast-rcnn
git remote add caffe https://github.com/BVLC/caffe.git  
git fetch caffe  
git config user.name "dmis"
git config user.email "dmis.dreamchallenge@gmail.com"
git merge caffe/master -m " "


# install dependencies
cd $WORKSPACE/py-faster-rcnn/caffe-fast-rcnn/python
pip install -r requirements.txt

#### move edited caffe files
cp $WORKSPACE/installation/pycaffe.Makefile.config $WORKSPACE/py-faster-rcnn/caffe-fast-rcnn/Makefile.config
rm $WORKSPACE/py-faster-rcnn/caffe-fast-rcnn/include/caffe/layers/python_layer.hpp
cp $WORKSPACE/installation/python_layer.hpp $WORKSPACE/py-faster-rcnn/caffe-fast-rcnn/include/caffe/layers/python_layer.hpp

# install libs
cd $WORKSPACE/py-faster-rcnn/lib && \
    make
# install caffe
cd $WORKSPACE/py-faster-rcnn/caffe-fast-rcnn && \
    make -j8 && make pycaffe

### move edited py-caffe files
cp $WORKSPACE/installation/proposal_layer.py $WORKSPACE/py-faster-rcnn/lib/rpn/proposal_layer.hpp

# get trained model
cd $WORKSPACE
wget http://infos.korea.ac.kr/crawl/model.tar.gz
tar -zxvf model.tar.gz

cd $WORKSPACE
chmod 777 py-faster-rcnn
rm model.tar.gz
