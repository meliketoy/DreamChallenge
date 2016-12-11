from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# default packages
import glob
import sys
import multiprocessing
import csv
import shutil
import traceback

from pprint import pprint
from timeit import default_timer as timer

# installed packages
import yaml
import dicom
import numpy as np

# implemented packages
import util

import Preprocessor
from   Preprocessor import alignment
from   Preprocessor import matcher
#from   Preprocessor import extractor


logger = util.build_logger()

class App(object):
    def __init__(self, **kwargs):
        self.args = kwargs['args']
        self.config = kwargs['config']

        # verify argument
        if args.dataset not in config['data'][args.corpus]:
            logger.error('Invalid data corpusr: {0}'.format(args.corpus))
            sys.exit(-1)

        self.data_dir = self.config['data'][args.corpus][args.dataset]
        #self.data_dir = self.config['data'][args.dataset]

        self.proc_cnt = self.args.processor
        self.display_setups()

    """
    Build Image and Exam  Data from dicom files or metadata file
    """
    def build_metadata(self):
        logger.info('load dcm file list in {0}'.format(self.data_dir))

        return (self.__build_image_data_from_metadata(),
                self.__build_exams_data_from_metadata())


    def __build_image_data_from_metadata(self):
        config_metadata = self.config['data'][self.args.corpus]['metadata']
        cross_walk_file_path = '/'.join([
            config_metadata['dir'],
            config_metadata['images_crosswalk']
        ])

        s_dict = dict()
        with open(cross_walk_file_path, 'rt') as f:
            walker = csv.DictReader(f, delimiter='\t')
            for row in walker:
                k = (row['subjectId'], row['examIndex'])

                if k not in s_dict:
                    s_dict[k] = dict()
                if row['view'] not in s_dict[k]:
                    s_dict[k][row['view']] = dict()

                s_dict[k][row['view']][row['laterality']] = {
                    'img_idx': row['imageIndex'],
                    'fname'  : row['filename']
                }

                if 'cancer' in row:
                    s_dict[k][row['view']][row['laterality']]['cancer'] = row['cancer']

        return s_dict

    def __build_exams_data_from_metadata(self):
        try:
            config_metadata = self.config['data'][self.args.corpus]['metadata']
            exams_file_path = '/'.join([
                config_metadata['dir'],
                config_metadata['exams_metadata']
            ])

            e_dict = dict()
            with open(exams_file_path, 'rt') as f:
                walker = csv.DictReader(f, delimiter='\t')
                for row in walker:
                    k = (row['subjectId'], row['examIndex'])

                    e_dict[k] = row

            return e_dict
        except:
            return None

    """
    Preprocessing Main Pipeline (end-point)
    """
    def preprocessing(self):
        # subject_dict / exams_dict
        s_dict, self.e_dict = self.build_metadata()
        logger.info('The size of data: {0}'.format(len(s_dict)))

        if self.args.valid == 1:
            s_dict_train, s_dict_valid = self.split_train_valid(s_dict)
            logger.info('preprocessing start : {0}'.format(self.args.dataset))
            self.preprocessing_dataset(s_dict_train, self.args.dataset)
            logger.info('preprocessing start : {0}'.format('val'))
            self.preprocessing_dataset(s_dict_valid, 'val')
        else:
            logger.info('preprocessing start : {0}'.format(self.args.dataset))
            self.preprocessing_dataset(s_dict, self.args.dataset)

    def preprocessing_dataset(self, s_dict, dataset_name):
        tmp_dir    = '/'.join([
            self.config['resultDir'],
            'tmp'
        ])
        target_dir = '/'.join([
            self.config['resultDir'],
            self.args.corpus,
            dataset_name
        ])
        try:    shutil.rmtree(target_dir)
        except: pass

        util.mkdir(target_dir)
        util.mkdir(tmp_dir)


        logger.debug('split subject_dict start')
        if self.proc_cnt == 1:
            proc_feeds = [s_dict]
        else:
            # TODO:round? floor?
            feed_size = int(len(s_dict) / self.proc_cnt) + 1
            proc_feeds = util.split_dict(s_dict, feed_size)
        logger.debug('split subject_dict finish')

        procs = list()
        for proc_num in range(self.proc_cnt):
            proc_feed = proc_feeds[proc_num]

            proc = multiprocessing.Process(target=self.preprocessing_single_proc,
                    args=(proc_feed, self.data_dir, target_dir, tmp_dir, proc_num))

            procs.append(proc)
            proc.start()

        for proc in procs:
            proc.join()

        self.merge_metadata(target_dir, tmp_dir)

    def split_train_valid(self, s_dict):
        s_size = len(s_dict)
        train_size = int(s_size * 0.8)

        train_valid = util.split_dict(s_dict, train_size)

        return train_valid[0],train_valid[1]

    def preprocessing_single_proc(self, s_dict, source_dir, target_dir, tmp_dir, proc_num=0):
        # create extractors based on configuration
        ext = { target: extractor.facotry(
                            target,
                            self.config['modules']['roi'])
                for target in self.config['modules']['roi']['targets'] }

        logger.info('Proc{proc_num} start'.format(proc_num = proc_num))
        start = timer()

        meta_f = open('/'.join([tmp_dir, 'metadata_' + str(proc_num) + '.tsv']),'w')
        for (s_id, exam_idx) in s_dict.keys():
            k = (s_id, exam_idx)

            logger.debug('Proc{proc_num} : Preprocessing... {s_id} --> {target_dir}'.format(
                proc_num = proc_num,
                s_id = s_id,
                target_dir = target_dir))

            dicom_dict = s_dict[k]
            for v in dicom_dict.keys():
                for l in dicom_dict[v].keys():
                    info = dicom_dict[v][l]
                    filename = info['fname']
                    dcm = dicom.read_file('/'.join([source_dir, info['fname']]))

                    # run image preprocessing and save result
                    img = self.preprocessing_dcm(dcm, l, ext, proc_num)

                    if self.e_dict == None:
                        cancer_label = info['cancer']
                    else:
                        cancer_label = self.e_dict[k]['cancer' + l]

                    self.write_img(img, cancer_label, {
                        's_id': s_id,
                        'exam_idx': exam_idx,
                        'v': v,
                        'l': l
                        }, target_dir)

                    meta_f.write('\t'.join([s_id, exam_idx, v, l, cancer_label]))
                    meta_f.write('\n')
        meta_f.close()

        logger.info('Proc{proc_num} Finish : size[{p_size}]\telapsed[{elapsed_time}]'.format(
            proc_num = proc_num,
            p_size = len(s_dict),
            elapsed_time = timer() - start
            ))

    def preprocessing_dcm(self, dcm, l, ext, proc_num=0):
        logger.debug('start: {method}'.format(method='handle dcm'))

        # convert dicom to image and preprocess image
        imgs = dict()

        # convert dicom to (gray scale) image
        imgs['gray'] = Preprocessor.dcm2cvimg(dcm, proc_num)

        # run pipeline before roi extraction
        for module in self.config['pipeline']['prev_roi']:
            logger.debug('Run module  : {method}'.format(method=method))
            imgs['gray'] = getattr(Preprocessor, module)(
                    imgs['gray'],
                    self.config['modules'][module]
            )

        # run roi extraction
        if self.config['pipeline']['roi']:
            logger.debug('Run module  : ROI extraction')
            imgs['rgb'] = Preprocessor.gray2rgb(imgs['gray'])
            for target in self.config['roi']['targets']:
                imgs[target] = ext[target].get_mask(imgs['rgb'])

        # create image channel stack
        im_layers = []
        for channel in self.config['channel']:
            im_layer = imgs[channel]
            # if current im_layer is not single channel
            if im_layer.shape[2] != 1:
                im_layer = Preprocessor.img2gray(im_layer)
            im_layers.append(im_layer)
        im = np.stack(im_layers, axis=-1)


        # run pipeline after roi extraction
        for module in self.config['pipeline']['prev_roi']:
            logger.debug('Run module  : {method}'.format(method=method))
            im = getattr(Preprocessor, module)(
                    im,
                    self.config['modules'][module]
            )

        """
        og_gray = Preprocessor.dcm2cvimg(dcm, proc_num)
        og_gray = Preprocessor.trim(og_gray)
        if l == 'R':
            og_gray = Preprocessor.flip(og_gray)

        og_rgb  = Preprocessor.gray2rgb(og_gray)

        # mass layer
        mass= ext['mass'].get_mask(og_rgb)
        # calification layer
        cal = np.zeros(og_gray.shape)

        # integrating layers
        im = np.stack((
            og_gray,
            Preprocessor.img2gray(mass),
            og_gray
        ), axis= -1)

        # crop - based on ROI
        nz_coor = extractor.find_nonezero(im)
        nz_coor = extractor.merge_coord(nz_coor)
        im = extractor.crop_inner(nz_coor, og_gray, 1024)
        # crop - based on center
        coor = extractor.find_center(im)
        im   = extractor.crop(coor, im)

        # padding
        try:
            im = Preprocessor.padding(im)
            im = Preprocessor.resize(im)
        except Exception:
            pass
            traceback.print_exc()
            print(im.shape)
        """

        return im

    def write_img(self, img, cancer_label, meta, target_dir):
        if self.args.form == 'class':
            img_dir = '/'.join([target_dir, cancer_label])
            img_path= '/'.join([img_dir,
                                '_'.join([
                                    meta['s_id'],
                                    meta['exam_idx'],
                                    meta['v'],
                                    meta['l']
                                    ]) + '.png'
                                ])
        elif self.args.form == 'robust':
            img_dir = '/'.join([target_dir,
                                meta['s_id'],
                                meta['exam_idx'],
                                meta['l']])
            img_path= '/'.join([img_dir, v + '.png'])
        else:
            logger.error('invalid form: {form}'.format(form=self.args.form))
            sys.exit(-1)

        util.mkdir(img_dir)
        Preprocessor.write_img(img_path, img)

    def merge_metadata(self, target_dir, tmp_dir):
        img_cnt = 0

        # merge tmp merge data
        metadata_f = open('/'.join([target_dir, 'metadata.tsv']), 'w')
        for metadata_tmp in glob.glob('/'.join([tmp_dir, 'metadata_*.tsv'])):
            metadata_tmp_f = open(metadata_tmp, 'r')
            metadata_f.write(metadata_tmp_f.read())
            img_cnt += 1

        return img_cnt

    def display_setups(self):
        from colorama import init
        from colorama import Fore, Back, Style
        init()

        print(Fore.CYAN + "# ENVIRONMENT" + Style.RESET_ALL)
        print("|-- {:10}".format('processor'),  self.args.processor)
        print("|-- {:10}".format('gpu'),        self.args.gpu)

        print(Fore.CYAN + "# DATASET" + Style.RESET_ALL)
        print("|-- {:10}".format('corpus'),     self.args.corpus)
        print("|-- {:10}".format('dataset'),    self.args.dataset)

        print(Fore.CYAN + "# SAMPLING" + Style.RESET_ALL)
        print("|-- {:10}".format('method'),     self.config['sampling'])

        print(Fore.CYAN + "# PRE-PROCESSING PIPELINE" + Style.RESET_ALL)
        for module in self.config['pipeline']['prev_roi']:
            print("\t" + Style.BRIGHT + module + Style.RESET_ALL)
            print("\t|\t> ", self.config['modules'][module])
        if self.config['pipeline']['roi']:
            print("\troi extraction " + Style.BRIGHT + "(ON)" + Style.RESET_ALL)
            for target in self.config['modules']['roi']['targets']:
                print("\t\t|-- " + target, self.config['modules']['roi'][target])
                #print("\t|\t> ", self.config['modules']['roi'][target])
        else:
            print("\t|-- roi extraction (OFF)")
        for module in self.config['pipeline']['post_roi']:
            print("\t" + Style.BRIGHT + module + Style.RESET_ALL)
            print("\t|\t> ", self.config['modules'][module])

        print(Fore.CYAN + "# RESULT" + Style.RESET_ALL)
        print("|-- generating form   ", self.args.form)
        print("|-- generating valid  ", self.args.valid)
        print("|-- directory")
        print("\t|-- {:10}".format('result'),     self.config['resultDir'])
        print("\t|-- {:10}".format('log'),        self.config['logDir'])

if __name__ == '__main__':
    import ConfigParser
    import argparse

    # program argument
    parser = argparse.ArgumentParser()
    #### Environment
    parser.add_argument('-p', '--processor',
            type=int,
            required=False,
            default = util.get_cpu_cnt(),
            help='how many use processores')
    parser.add_argument('-g', '--gpu',
            type = int,
            required=False,
            default=1,
            help='use GPU? in ROI extraction')
    #### Dataset
    parser.add_argument('-c', '--corpus',
            required=True,
            help='will be used in preprocessing phase')
    parser.add_argument('-d', '--dataset',
            required=True,
            help='dataset in corpus')
    #### Result
    parser.add_argument('-f', '--form',
            required=True,
            help='class, robust')
    parser.add_argument('-v', '--valid',
            type=int,
            required=False,
            help='generate validset from training')
    # TODO: remove -b flag
    parser.add_argument('-b', '--balanced',
            required=False,
            help='force balancing train & test')

    args = parser.parse_args()

    # load program configuration
    with open('config/preprocessing.yaml', 'rt') as f:
        config = yaml.safe_load(f.read())

    preprocessor = App(args=args, config=config)
    #preprocessor.preprocessing()
