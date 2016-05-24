__author__ = 'yuxiang'

import datasets
import datasets.mot_tracking
import os
import PIL
import datasets.imdb
import numpy as np
import scipy.sparse
from utils.cython_bbox import bbox_overlaps
from utils.boxes_grid import get_boxes_grid
import subprocess
import cPickle
from fast_rcnn.config import cfg
import math
from rpn_msr.generate_anchors import generate_anchors

class mot_tracking(datasets.imdb):
    def __init__(self, image_set, seq_name, mot_tracking_path=None):
        datasets.imdb.__init__(self, 'mot_tracking_' + image_set + '_' + seq_name)
        self._image_set = image_set
        self._seq_name = seq_name
        self._mot_tracking_path = self._get_default_path() if mot_tracking_path is None \
                            else mot_tracking_path
        self._data_path = os.path.join(self._mot_tracking_path, image_set)
        self._classes = ('__background__', 'Pedestrian')
        self._class_to_ind = dict(zip(self.classes, xrange(self.num_classes)))
        self._image_ext = '.jpg'
        self._image_index = self._load_image_set_index()
        # Default to roidb handler
        if cfg.IS_RPN:
            self._roidb_handler = self.gt_roidb
        else:
            self._roidb_handler = self.region_proposal_roidb

        # num of subclasses
        self._num_subclasses = 128 + 1

        # load the mapping for subcalss to class
        filename = os.path.join(self._mot_tracking_path, 'voxel_exemplars', 'train', 'mapping.txt')
        assert os.path.exists(filename), 'Path does not exist: {}'.format(filename)
        
        mapping = np.zeros(self._num_subclasses, dtype=np.int)
        with open(filename) as f:
            for line in f:
                words = line.split()
                subcls = int(words[0])
                mapping[subcls] = self._class_to_ind[words[1]]
        self._subclass_mapping = mapping

        self.config = {'top_k': 100000}

        # statistics for computing recall
        self._num_boxes_all = np.zeros(self.num_classes, dtype=np.int)
        self._num_boxes_covered = np.zeros(self.num_classes, dtype=np.int)
        self._num_boxes_proposal = 0

        assert os.path.exists(self._mot_tracking_path), \
                'mot_tracking path does not exist: {}'.format(self._mot_tracking_path)
        assert os.path.exists(self._data_path), \
                'Path does not exist: {}'.format(self._data_path)

    def image_path_at(self, i):
        """
        Return the absolute path to image i in the image sequence.
        """
        return self.image_path_from_index(self.image_index[i])

    def image_path_from_index(self, index):
        """
        Construct an image path from the image's "index" identifier.
        """

        image_path = os.path.join(self._data_path, index + self._image_ext)
        assert os.path.exists(image_path), \
                'Path does not exist: {}'.format(image_path)
        return image_path

    def _load_image_set_index(self):
        """
        Load the indexes listed in this dataset's image set file.
        """

        mot_train_seqs = ['TUD-Stadtmitte', 'TUD-Campus', 'PETS09-S2L1', \
            'ETH-Bahnhof', 'ETH-Sunnyday', 'ETH-Pedcross2', 'ADL-Rundle-6', \
            'ADL-Rundle-8', 'KITTI-13', 'KITTI-17', 'Venice-2']
        mot_train_nums = [179, 71, 795, 1000, 354, 837, 525, 654, 340, 145, 600]

        mot_test_seqs = ['TUD-Crossing', 'PETS09-S2L2', 'ETH-Jelmoli', \
            'ETH-Linthescher', 'ETH-Crossing', 'AVG-TownCentre', 'ADL-Rundle-1', \
            'ADL-Rundle-3', 'KITTI-16', 'KITTI-19', 'Venice-1']
        mot_test_nums = [201, 436, 440, 1194, 219, 450, 500, 625, 209, 1059, 450];

        if self._seq_name == 'train' or self._seq_name == 'trainval':

            assert self._image_set == 'train', 'Use train set in testing'

            if self._seq_name == 'train':
                seq_index = [0, 2, 3, 6, 8]
            else:
                seq_index = range(0, 11)

            # for each sequence
            image_index = []
            for i in xrange(len(seq_index)):
                seq_idx = seq_index[i]
                name = mot_train_seqs[seq_idx] 
                num = mot_train_nums[seq_idx]
                for j in xrange(num):
                    image_index.append('{:s}/img1/{:06d}'.format(name, j+1))
        else:
            # a single sequence
            if self._image_set == 'train':
                names = mot_train_seqs
            else:
                names = mot_test_seqs

            seq_num = -1
            for ix, name in enumerate(names):
                if self._seq_name == name:
                    seq_num = ix
                    break

            if self._image_set == 'train':
                num = mot_train_nums[seq_num]
            else:
                num = mot_test_nums[seq_num]
            image_index = []
            for i in xrange(num):
                image_index.append('{:s}/img1/{:06d}'.format(self._seq_name, i+1))

        return image_index

    def _get_default_path(self):
        """
        Return the default path where mot_tracking is expected to be installed.
        """
        return os.path.join(datasets.ROOT_DIR, 'data', 'MOT_Tracking')


    def gt_roidb(self):
        """
        Return the database of ground-truth regions of interest.
        """

        cache_file = os.path.join(self.cache_path, self.name + '_' + cfg.SUBCLS_NAME + '_gt_roidb.pkl')
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as fid:
                roidb = cPickle.load(fid)
            print '{} gt roidb loaded from {}'.format(self.name, cache_file)
            return roidb

        gt_roidb = [self._load_mot_voxel_exemplar_annotation(index)
                    for index in self.image_index]

        if cfg.IS_RPN:
            # print out recall
            for i in xrange(1, self.num_classes):
                print '{}: Total number of boxes {:d}'.format(self.classes[i], self._num_boxes_all[i])
                print '{}: Number of boxes covered {:d}'.format(self.classes[i], self._num_boxes_covered[i])
                print '{}: Recall {:f}'.format(self.classes[i], float(self._num_boxes_covered[i]) / float(self._num_boxes_all[i]))

        with open(cache_file, 'wb') as fid:
            cPickle.dump(gt_roidb, fid, cPickle.HIGHEST_PROTOCOL)
        print 'wrote gt roidb to {}'.format(cache_file)

        return gt_roidb


    def _load_mot_voxel_exemplar_annotation(self, index):
        """
        Load image and bounding boxes info from txt file in the mot voxel exemplar format.
        """
        if self._image_set == 'train':
            prefix = 'train'
        else:
            prefix = ''

        if prefix == '':
            lines = []
            lines_flipped = []
        else:
            filename = os.path.join(self._mot_tracking_path, cfg.SUBCLS_NAME, prefix, index + '.txt')
            if os.path.exists(filename):
                print filename

                # the annotation file contains flipped objects    
                lines = []
                lines_flipped = []
                with open(filename) as f:
                    for line in f:
                        words = line.split()
                        subcls = int(words[1])
                        is_flip = int(words[2])
                        if subcls != -1:
                            if is_flip == 0:
                                lines.append(line)
                            else:
                                lines_flipped.append(line)
            else:
                print filename + ' not exist'
                lines = []
                lines_flipped = []
        
        num_objs = len(lines)

        # store information of flipped objects
        assert (num_objs == len(lines_flipped)), 'The number of flipped objects is not the same!'
        gt_subclasses_flipped = np.zeros((num_objs), dtype=np.int32)
        
        for ix, line in enumerate(lines_flipped):
            words = line.split()
            subcls = int(words[1])
            gt_subclasses_flipped[ix] = subcls

        boxes = np.zeros((num_objs, 4), dtype=np.float32)
        gt_classes = np.zeros((num_objs), dtype=np.int32)
        gt_subclasses = np.zeros((num_objs), dtype=np.int32)
        overlaps = np.zeros((num_objs, self.num_classes), dtype=np.float32)
        subindexes = np.zeros((num_objs, self.num_classes), dtype=np.int32)
        subindexes_flipped = np.zeros((num_objs, self.num_classes), dtype=np.int32)

        for ix, line in enumerate(lines):
            words = line.split()
            cls = self._class_to_ind[words[0]]
            subcls = int(words[1])
            boxes[ix, :] = [float(n) for n in words[3:7]]
            gt_classes[ix] = cls
            gt_subclasses[ix] = subcls
            overlaps[ix, cls] = 1.0
            subindexes[ix, cls] = subcls
            subindexes_flipped[ix, cls] = gt_subclasses_flipped[ix]

        overlaps = scipy.sparse.csr_matrix(overlaps)
        subindexes = scipy.sparse.csr_matrix(subindexes)
        subindexes_flipped = scipy.sparse.csr_matrix(subindexes_flipped)

        if cfg.IS_RPN:
            if cfg.IS_MULTISCALE:
                # compute overlaps between grid boxes and gt boxes in multi-scales
                # rescale the gt boxes
                boxes_all = np.zeros((0, 4), dtype=np.float32)
                for scale in cfg.TRAIN.SCALES:
                    boxes_all = np.vstack((boxes_all, boxes * scale))
                gt_classes_all = np.tile(gt_classes, len(cfg.TRAIN.SCALES))

                # compute grid boxes
                s = PIL.Image.open(self.image_path_from_index(index)).size
                image_height = s[1]
                image_width = s[0]
                boxes_grid, _, _ = get_boxes_grid(image_height, image_width)

                # compute overlap
                overlaps_grid = bbox_overlaps(boxes_grid.astype(np.float), boxes_all.astype(np.float))
        
                # check how many gt boxes are covered by grids
                if num_objs != 0:
                    index = np.tile(range(num_objs), len(cfg.TRAIN.SCALES))
                    max_overlaps = overlaps_grid.max(axis = 0)
                    fg_inds = []
                    for k in xrange(1, self.num_classes):
                        fg_inds.extend(np.where((gt_classes_all == k) & (max_overlaps >= cfg.TRAIN.FG_THRESH[k-1]))[0])
                    index_covered = np.unique(index[fg_inds])

                    for i in xrange(self.num_classes):
                        self._num_boxes_all[i] += len(np.where(gt_classes == i)[0])
                        self._num_boxes_covered[i] += len(np.where(gt_classes[index_covered] == i)[0])
            else:
                assert len(cfg.TRAIN.SCALES_BASE) == 1
                scale = cfg.TRAIN.SCALES_BASE[0]
                feat_stride = 16
                # faster rcnn region proposal
                base_size = 16
                ratios = [3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25]
                scales = 2**np.arange(1, 6, 0.5)
                anchors = generate_anchors(base_size, ratios, scales)
                num_anchors = anchors.shape[0]

                # image size
                s = PIL.Image.open(self.image_path_from_index(index)).size
                image_height = s[1]
                image_width = s[0]

                # height and width of the heatmap
                height = np.round((image_height * scale - 1) / 4.0 + 1)
                height = np.floor((height - 1) / 2 + 1 + 0.5)
                height = np.floor((height - 1) / 2 + 1 + 0.5)

                width = np.round((image_width * scale - 1) / 4.0 + 1)
                width = np.floor((width - 1) / 2.0 + 1 + 0.5)
                width = np.floor((width - 1) / 2.0 + 1 + 0.5)

                # gt boxes
                gt_boxes = boxes * scale

                # 1. Generate proposals from bbox deltas and shifted anchors
                shift_x = np.arange(0, width) * feat_stride
                shift_y = np.arange(0, height) * feat_stride
                shift_x, shift_y = np.meshgrid(shift_x, shift_y)
                shifts = np.vstack((shift_x.ravel(), shift_y.ravel(),
                            shift_x.ravel(), shift_y.ravel())).transpose()
                # add A anchors (1, A, 4) to
                # cell K shifts (K, 1, 4) to get
                # shift anchors (K, A, 4)
                # reshape to (K*A, 4) shifted anchors
                A = num_anchors
                K = shifts.shape[0]
                all_anchors = (anchors.reshape((1, A, 4)) + shifts.reshape((1, K, 4)).transpose((1, 0, 2)))
                all_anchors = all_anchors.reshape((K * A, 4))

                # compute overlap
                overlaps_grid = bbox_overlaps(all_anchors.astype(np.float), gt_boxes.astype(np.float))
        
                # check how many gt boxes are covered by anchors
                if num_objs != 0:
                    max_overlaps = overlaps_grid.max(axis = 0)
                    fg_inds = []
                    for k in xrange(1, self.num_classes):
                        fg_inds.extend(np.where((gt_classes == k) & (max_overlaps >= cfg.TRAIN.FG_THRESH[k-1]))[0])

                    for i in xrange(self.num_classes):
                        self._num_boxes_all[i] += len(np.where(gt_classes == i)[0])
                        self._num_boxes_covered[i] += len(np.where(gt_classes[fg_inds] == i)[0])

        return {'boxes' : boxes,
                'gt_classes': gt_classes,
                'gt_subclasses': gt_subclasses,
                'gt_subclasses_flipped': gt_subclasses_flipped,
                'gt_overlaps': overlaps,
                'gt_subindexes': subindexes, 
                'gt_subindexes_flipped': subindexes_flipped, 
                'flipped' : False}


    def region_proposal_roidb(self):
        """
        Return the database of regions of interest.
        Ground-truth ROIs are also included.

        This function loads/saves from/to a cache file to speed up future calls.
        """
        cache_file = os.path.join(self.cache_path,
                                  self.name + '_' + cfg.SUBCLS_NAME + '_' + cfg.REGION_PROPOSAL + '_region_proposal_roidb.pkl')

        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as fid:
                roidb = cPickle.load(fid)
            print '{} roidb loaded from {}'.format(self.name, cache_file)
            return roidb

        if self._image_set != 'test':
            gt_roidb = self.gt_roidb()

            print 'Loading region proposal network boxes...'
            model = 'train/'
            rpn_roidb = self._load_rpn_roidb(gt_roidb, model)
            print 'Region proposal network boxes loaded'
            roidb = datasets.imdb.merge_roidbs(rpn_roidb, gt_roidb)
        else:
            print 'Loading region proposal network boxes...'
            model = 'test/'
            roidb = self._load_rpn_roidb(None, model)
            print 'Region proposal network boxes loaded'

        print '{} region proposals per image'.format(self._num_boxes_proposal / len(self.image_index))

        with open(cache_file, 'wb') as fid:
            cPickle.dump(roidb, fid, cPickle.HIGHEST_PROTOCOL)
        print 'wrote roidb to {}'.format(cache_file)

        return roidb


    def _load_rpn_roidb(self, gt_roidb, model):
        # set the prefix
        prefix = model

        box_list = []
        for index in self.image_index:
            filename = os.path.join(self._mot_tracking_path, 'region_proposals',  prefix, index + '.txt')
            assert os.path.exists(filename), \
                'RPN data not found at: {}'.format(filename)
            print filename
            raw_data = np.loadtxt(filename, dtype=float)
            if len(raw_data.shape) == 1:
                if raw_data.size == 0:
                    raw_data = raw_data.reshape((0, 5))
                else:
                    raw_data = raw_data.reshape((1, 5))

            x1 = raw_data[:, 0]
            y1 = raw_data[:, 1]
            x2 = raw_data[:, 2]
            y2 = raw_data[:, 3]
            score = raw_data[:, 4]
            inds = np.where((x2 > x1) & (y2 > y1))[0]
            raw_data = raw_data[inds,:4]
            self._num_boxes_proposal += raw_data.shape[0]
            box_list.append(raw_data)

        return self.create_roidb_from_box_list(box_list, gt_roidb)

    def evaluate_detections(self, all_boxes, output_dir):

        # for each image
        for im_ind, index in enumerate(self.image_index):
            filename = os.path.join(output_dir, '{:06d}.txt'.format(im_ind+1))
            print 'Writing mot_tracking results to file ' + filename
            with open(filename, 'wt') as f:
                # for each class
                for cls_ind, cls in enumerate(self.classes):
                    if cls == '__background__':
                        continue
                    dets = all_boxes[cls_ind][im_ind]
                    if dets == []:
                        continue
                    for k in xrange(dets.shape[0]):
                        subcls = int(dets[k, 5])
                        cls_name = self.classes[self.subclass_mapping[subcls]]
                        assert (cls_name == cls), 'subclass not in class'
                        f.write('{:d} -1 {:f} {:f} {:f} {:f} {:f} -1 -1 -1\n'.format(\
                                 im_ind+1, dets[k, 0], dets[k, 1], dets[k, 2]-dets[k, 0], dets[k, 3]-dets[k, 1], dets[k, 4]))

    # write detection results into one file
    def evaluate_detections_one_file(self, all_boxes, output_dir):

        # open results file
        filename = os.path.join(output_dir, self._seq_name+'.txt')
        print 'Writing all mot_tracking results to file ' + filename
        with open(filename, 'wt') as f:
            # for each image
            for im_ind, index in enumerate(self.image_index):
                # for each class
                for cls_ind, cls in enumerate(self.classes):
                    if cls == '__background__':
                        continue
                    dets = all_boxes[cls_ind][im_ind]
                    if dets == []:
                        continue
                    for k in xrange(dets.shape[0]):
                        subcls = int(dets[k, 5])
                        cls_name = self.classes[self.subclass_mapping[subcls]]
                        assert (cls_name == cls), 'subclass not in class'
                        f.write('{:d} -1 {:f} {:f} {:f} {:f} {:f} -1 -1 -1\n'.format(\
                                 im_ind+1, dets[k, 0], dets[k, 1], dets[k, 2]-dets[k, 0], dets[k, 3]-dets[k, 1], dets[k, 4]))

    def evaluate_proposals(self, all_boxes, output_dir):
        # for each image
        for im_ind, index in enumerate(self.image_index):
            filename = os.path.join(output_dir, '{:06d}.txt'.format(im_ind+1))
            print 'Writing mot_tracking results to file ' + filename
            with open(filename, 'wt') as f:
                # for each class
                for cls_ind, cls in enumerate(self.classes):
                    if cls == '__background__':
                        continue
                    dets = all_boxes[cls_ind][im_ind]
                    if dets == []:
                        continue
                    for k in xrange(dets.shape[0]):
                        if dets[k, 2] - dets[k, 0] > 0 and dets[k, 3] - dets[k, 1] > 0:
                            f.write('{:f} {:f} {:f} {:f} {:.32f}\n'.format(\
                                 dets[k, 0], dets[k, 1], dets[k, 2], dets[k, 3], dets[k, 4]))

    # write proposals into one file
    def evaluate_proposals_one_file(self, all_boxes, output_dir):

        # open results file
        filename = os.path.join(output_dir, self._seq_name+'.txt')
        print 'Writing all mot_tracking results to file ' + filename
        with open(filename, 'wt') as f:
            # for each image
            for im_ind, index in enumerate(self.image_index):
                # for each class
                for cls_ind, cls in enumerate(self.classes):
                    if cls == '__background__':
                        continue
                    dets = all_boxes[cls_ind][im_ind]
                    if dets == []:
                        continue
                    for k in xrange(dets.shape[0]):
                        if dets[k, 2] - dets[k, 0] > 0 and dets[k, 3] - dets[k, 1] > 0:
                            f.write('{:d} -1 {:f} {:f} {:f} {:f} {:f} -1 -1 -1\n'.format(\
                                 im_ind+1, dets[k, 0], dets[k, 1], dets[k, 2]-dets[k, 0], dets[k, 3]-dets[k, 1], dets[k, 4]))


    def evaluate_proposals_msr(self, all_boxes, output_dir):
        # for each image
        for im_ind, index in enumerate(self.image_index):
            filename = os.path.join(output_dir, '{:06d}.txt'.format(im_ind+1))
            print 'Writing mot_tracking results to file ' + filename
            with open(filename, 'wt') as f:
                dets = all_boxes[im_ind]
                if dets == []:
                    continue
                for k in xrange(dets.shape[0]):
                    f.write('{:f} {:f} {:f} {:f} {:.32f}\n'.format(dets[k, 0], dets[k, 1], dets[k, 2], dets[k, 3], dets[k, 4]))


if __name__ == '__main__':
    d = datasets.mot_tracking('train', 'TUD-Stadtmitte')
    res = d.roidb
    from IPython import embed; embed()