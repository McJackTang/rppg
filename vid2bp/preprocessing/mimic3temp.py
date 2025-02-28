import os
import wfdb
import random

from tqdm import tqdm
import multiprocessing as mp
# from multiprocessing import Process, shared_memory, Semaphore
import numpy as np
import matplotlib.pyplot as plt
# import vid2bp.preprocessing.utils.multi_processing as multi
# import vid2bp.preprocessing.utils.data_shuffler as ds
import time
import h5py
import datetime as dt
import vid2bp.preprocessing.utils.signal_utils as su
# import vid2bp.preprocessing.utils.sutemp as sutemp
import vid2bp.preprocessing.utils.math_module as mm

import heartpy.peakdetection as hp_peak
from heartpy.datautils import rolling_mean
from heartpy.filtering import filter_signal
import vid2bp.preprocessing.signal_cleaner as sc
# from scipy.ndimage import gaussian_filter1d
import vid2bp.preprocessing.mimiciii_matched as match
import vid2bp.preprocessing.normalize_preprocessing as add_preprocessing
import pandas as pd
import json


with open('config/parameter.json') as f:
    json_data = json.load(f)
    # param = json_data.get("parameters")
    channels = json_data.get("parameters").get("in_channels")
    gender_info = json_data.get("parameters").get("gender")

'''
signal_utils.py 로 이동해야 할 함수
'''
from scipy import signal


def derivative(x):
    deriv = np.append(x[1:], x[-1]) - x
    deriv[-1] = np.mean(deriv[-3:-2])
    return deriv


def channel_aggregator(x, dx, ddx):
    return np.concatenate((x, dx, ddx), axis=0)


def down_sampling(original_signal, fs: int = 125, target_fs: int = 60):
    '''
    :param original_signal: signal to be down-sampled
    :param fs: original sampling rate
    :param target_fs: target sampling rate
    :return:
    '''
    # if fs == target_fs:
    #     return original_signal
    # else:
    #     return signal.resample(original_signal, int(len(original_signal) * target_fs / fs))
    # return signal.resample(original_signal, int(len(original_signal) * target_fs / fs))
    # resampled_signal = np.array(original_signal)[15:735:int(fs / target_fs)]
    # return np.array(original_signal)[15:735:int(fs / target_fs)]
    return original_signal


def signal_QC(ple_chunk, abp_chunk):
    if np.isnan(ple_chunk).any() or np.isnan(abp_chunk).any() or \
            (np.var(abp_chunk) < 1) or \
            (not (np.sign(abp_chunk) > 0.0).all()) or \
            np.min(abp_chunk) < 60 or np.max(abp_chunk) > 240:
        return False
    else:
        # plt.plot(abp_chunk)
        # plt.show()
        return True


def get_process_num(target_num: int):
    """
    :param target_num: total number of task(segment) to be preprocessed
    :return: process_num: number of process to be used
    """

    divisors = []
    for i in range(1, int(target_num ** 0.5) + 1):
        if target_num % i == 0:
            divisors.append(i)
            if i != target_num // i:
                divisors.append(target_num // i)
    available_divisor = [x for x in divisors if x < os.cpu_count()]
    # if np.max(available_divisor) < os.cpu_count() // 2:
    #     process_num = os.cpu_count()
    # else:
    #     process_num = np.max(available_divisor)
    # if process_num < os.cpu_count():
    #     if process_num % 2 == 0:
    #         return process_num
    #     else:
    #         return process_num + 1
    # # if np.max(available_divisor) < os.cpu_count() // 2:
    # #     return os.cpu_count()
    # # else:
    # #     if np.max(available_divisor) % 2 == 0 and np.max(available_divisor) < os.cpu_count():
    # #         return np.max(available_divisor)
    # #     else:
    # #         return np.max(available_divisor) + 1

    return os.cpu_count() if np.max(available_divisor) < os.cpu_count() // 2 else np.max(available_divisor)


def list_shuffler(path_list):
    """
    :param path_list: list of path to be shuffled
    :return: shuffled path_list
    """
    shuffle_cnt = random.randint(len(path_list)*2, len(path_list) * 3)
    for _ in tqdm(range(shuffle_cnt), desc='shuffling'):
        i = random.randint(0, len(path_list) - 1)
        j = random.randint(0, len(path_list) - 1)
        path_list[i], path_list[j] = path_list[j], path_list[i]
    random.shuffle(path_list)
    return path_list


def get_segments_per_person(read_path: str):
    """
    :param read_path: path of a single patient (e.g. /hdd/hdd0/dataset/bpnet/adults/physionet.org/files/mimic3wdb/1.0/30/3001937_11)
    :return: all_file_paths: list of all segments of a single patient
    """
    all_file_paths = []
    for root, dirs, files in os.walk(read_path):
        for file in files:
            if file.endswith('.hea'):
                all_file_paths.append(root + '/' + file)
    all_file_paths = [p for p in all_file_paths if
                      p.endswith('.hea') and ('_' in p.split('/')[-1]) and ('layout' not in p)]
    random.shuffle(all_file_paths)
    return all_file_paths


def get_total_segment_path(read_path: str, gender: int):
    """
    * if single patient have too many records,
        randomly select 5(or any number you like) records to prevent over-fitting to single patient.
    param: read_path: path of the raw dataset (e.g. /hdd/hdd0/dataset/bpnet/adults/physionet.org/files/mimic3wdb/1.0)
    return: all_shuffled_data_path: shuffled list of all patient's segments
    """
    total_patient_path = []
    train_shuffled_path, val_shuffled_path, test_shuffled_path = [], [], []
    # get all patient's path
    for root, dirs, files in os.walk(read_path):
        if len(files) > 0:
            total_patient_path.append(root)
    total_patient_path = [p for p in total_patient_path if '_' in p.split('/')[-1]]
    pid = [int(t.split('/')[-1].split('_')[0][-5:]) for t in total_patient_path]
    # for p in pid:
    #     pp[str(p)]
    pid_list = [[int(t.split('/')[-1].split('_')[0][-5:]), t] for t in total_patient_path]
    patient_info, patient_df = match.get_patients_info(gender, pid, pid_list)

    # total_patient_info = match.get_patients_gender()
    # p_keys = total_patient_info.keys()
    # total_patient_path = [t for t in total_patient_path if t.split('/')[-1].split('_')[0][-5:] in p_keys]
    # for t in total_patient_path:
    #     if t.split('/')[-2].split('_')[-5:] in p_keys:
    #         print('test')
    print('shuffling all patient path...')
    total_patient_path = list_shuffler(total_patient_path)


    # split train, val, test
    train_patient_num = int(len(total_patient_path) * 0.8)
    val_patient_num = int(len(total_patient_path) * 0.1)
    train_path = total_patient_path[:train_patient_num]
    val_path = total_patient_path[train_patient_num:train_patient_num + val_patient_num]
    test_path = total_patient_path[train_patient_num + val_patient_num:]

    # get train segments per patient
    print('get_train_segment_path...')
    for tr in tqdm(train_path, desc='Train_segment'):
        train_segments = get_segments_per_person(tr)
        if len(train_segments) > 15:
            reduced_train_segments = random.sample(train_segments, 15)
            train_shuffled_path.extend(reduced_train_segments)
        else:
            train_shuffled_path.extend(train_segments)
    # get val segments per patient
    print('get_validation_segment_path...')
    for v in tqdm(val_path, desc='Val_segment'):
        val_segments = get_segments_per_person(v)
        if len(val_segments) > 15:
            reduced_val_segments = random.sample(val_segments, 15)
            val_shuffled_path.extend(reduced_val_segments)
        else:
            val_shuffled_path.extend(val_segments)
    # get test segments per patient
    print('get_test_segment_path...')
    for te in tqdm(test_path, desc='Test_segment'):
        test_segments = get_segments_per_person(te)
        if len(test_segments) > 15:
            reduced_test_segments = random.sample(test_segments, 15)
            test_shuffled_path.extend(reduced_test_segments)
        else:
            test_shuffled_path.extend(test_segments)
    print('total number of patients: ', len(total_patient_path))
    print('total number of train patients: ', len(train_path))
    print('total number of val patients: ', len(val_path))
    print('total number of test patients: ', len(test_path))
    print('total number of train segments: ', len(train_shuffled_path))
    print('total number of val segments: ', len(val_shuffled_path))
    print('total number of test segments: ', len(test_shuffled_path))
    return list_shuffler(train_shuffled_path), list_shuffler(val_shuffled_path), list_shuffler(test_shuffled_path), patient_info, patient_df


def find_channel_idx(path):
    """
    param: path: path of a segment (e.g. /hdd/hdd0/dataset/bpnet/adults/physionet.org/files/mimic3wdb/1.0/30/3001937_11)
    return: idx: index of the ple, abp channel
    """
    record = wfdb.rdrecord(path)
    channel_names = record.sig_name
    ple_idx = [p for p in range(len(channel_names)) if channel_names[p] == 'PLETH'][0]
    abp_idx = [a for a in range(len(channel_names)) if channel_names[a] == 'ABP'][0]

    return ple_idx, abp_idx


# def read_record(path):
def length_checker(target_signal, length):
    if type(target_signal) != np.ndarray or len(target_signal) < length:
        return False
    else:
        return True


def signal_slicer(target_signal, fs=125, t=8, overlap=2):
    return_signal_list = []
    while length_checker(target_signal, t * fs):
        return_signal_list.append(target_signal[:t * fs])
        target_signal = target_signal[(t - overlap) * fs:]
    return np.array(return_signal_list)


def nan_detector(target_signal):
    nan_idx = np.argwhere(np.isnan(target_signal))
    return nan_idx


def nan_checker(target_signal):
    # return if signal has nan
    return np.isnan(target_signal).any(), len(np.where(np.isnan(target_signal))[0])


def nan_interpolator(target_signal):
    # not used
    nan_idx = nan_detector(target_signal)
    nan_idx = nan_idx.reshape(-1)
    for idx in nan_idx:
        target_signal[idx] = np.nanmean(target_signal)
    return target_signal


def flat_signal_checker(target_signal, t=2, threshold=0.1, slicing=True):
    # return True if flat
    if slicing:
        target_signal = signal_slicer(target_signal, t=t, overlap=0)
        for sliced_signal in target_signal:
            if np.std(sliced_signal) < threshold:
                return True
    else:
        if np.std(target_signal) < threshold:
            return True
    return False


def signal_shifter(target_signal, gap):
    shifted_signal = np.zeros_like(target_signal)
    if gap > 0:
        shifted_signal[:len(target_signal) - gap] = target_signal[gap:]
        shifted_signal = shifted_signal[:-gap]
    else:
        shifted_signal[-gap:] = target_signal[:len(target_signal) + gap]
        shifted_signal = shifted_signal[-gap:]
    return shifted_signal


def correlation_checker(target_signal, reference_signal):
    return np.corrcoef(target_signal, reference_signal)[0, 1]


def signal_matcher(raw_abp, raw_ple, abp_signal, ple_signal, abp_peaks, ple_peaks, abp_bottoms, ple_bottoms,
                   threshold=0.9):
    best_corr = 0
    best_abp = []
    best_ple = []
    best_gap = 0
    gaps = []
    if len(abp_peaks) > len(ple_peaks):
        for peak_index in range(len(ple_peaks)):
            if peak_index - 1 > 0:
                gaps.append(abp_peaks[peak_index - 1] - ple_peaks[peak_index])

            gaps.append(abp_peaks[peak_index] - ple_peaks[peak_index])

            if peak_index + 1 < len(abp_peaks):
                gaps.append(abp_peaks[peak_index + 1] - ple_peaks[peak_index])
        for gap in gaps:
            matched_ple_signal = signal_shifter(ple_signal, gap)
            if gap > 0:
                matched_abp_signal = abp_signal[:-gap]
            else:
                matched_abp_signal = abp_signal[-gap:]
            if length_checker(matched_abp_signal, 6 * 125) and length_checker(matched_ple_signal, 6 * 125):
                correlation = correlation_checker(matched_abp_signal, matched_ple_signal)
                if correlation > best_corr:
                    best_gap = gap
                    best_corr = correlation
                    best_abp = matched_abp_signal
                    best_ple = matched_ple_signal
        raw_ple = signal_shifter(raw_ple, best_gap)
        if best_gap > 0:
            raw_abp = raw_abp[:-best_gap]
            matched_abp_peaks = abp_peaks[np.argwhere(abp_peaks < len(best_abp)).reshape(-1)]
            matched_ple_peaks = ple_peaks[np.argwhere(ple_peaks > best_gap).reshape(-1)] - best_gap
            matched_abp_bottoms = abp_bottoms[np.argwhere(abp_bottoms < len(best_abp)).reshape(-1)]
            matched_ple_bottoms = ple_bottoms[np.argwhere(ple_bottoms > best_gap).reshape(-1)] - best_gap
        else:
            raw_abp = raw_abp[-best_gap:]
            matched_abp_peaks = abp_peaks[np.argwhere(abp_peaks > -best_gap).reshape(-1)] + best_gap
            matched_ple_peaks = ple_peaks[np.argwhere(ple_peaks < len(best_ple) + best_gap).reshape(-1)]
            matched_abp_bottoms = abp_bottoms[np.argwhere(abp_bottoms > -best_gap).reshape(-1)] + best_gap
            matched_ple_bottoms = ple_bottoms[np.argwhere(ple_bottoms < len(best_ple) + best_gap).reshape(-1)]
    else:
        for peak_index in range(len(abp_peaks)):
            if peak_index - 1 > 0:
                gaps.append(ple_peaks[peak_index - 1] - abp_peaks[peak_index])

            gaps.append(ple_peaks[peak_index] - abp_peaks[peak_index])

            if peak_index + 1 < len(ple_peaks):
                gaps.append(ple_peaks[peak_index + 1] - abp_peaks[peak_index])

        for gap in gaps:
            matched_abp_signal = signal_shifter(abp_signal, gap)
            if gap > 0:
                matched_ple_signal = ple_signal[:-gap]
            else:
                matched_ple_signal = ple_signal[-gap:]
            if length_checker(matched_abp_signal, 6 * 125) and length_checker(matched_ple_signal, 6 * 125):
                correlation = correlation_checker(matched_abp_signal, matched_ple_signal)
                if correlation > best_corr:
                    best_gap = gap
                    best_corr = correlation
                    best_abp = matched_abp_signal
                    best_ple = matched_ple_signal
        raw_abp = signal_shifter(raw_abp, best_gap)
        if best_gap > 0:
            raw_ple = raw_ple[:-best_gap]
            matched_ple_peaks = ple_peaks[np.argwhere(ple_peaks < len(best_ple)).reshape(-1)]
            matched_abp_peaks = abp_peaks[np.argwhere(abp_peaks > best_gap).reshape(-1)] - best_gap
            matched_ple_bottoms = ple_bottoms[np.argwhere(ple_bottoms < len(best_ple)).reshape(-1)]
            matched_abp_bottoms = abp_bottoms[np.argwhere(abp_bottoms > best_gap).reshape(-1)] - best_gap
        else:
            raw_ple = raw_ple[-best_gap:]
            matched_ple_peaks = ple_peaks[np.argwhere(ple_peaks > -best_gap).reshape(-1)] + best_gap
            matched_abp_peaks = abp_peaks[np.argwhere(abp_peaks < len(best_abp) + best_gap).reshape(-1)]
            matched_ple_bottoms = ple_bottoms[np.argwhere(ple_bottoms > -best_gap).reshape(-1)] + best_gap
            matched_abp_bottoms = abp_bottoms[np.argwhere(abp_bottoms < len(best_abp) + best_gap).reshape(-1)]

    if best_corr < threshold:
        return False, None, None, None, None, None, None, None, None, None
    else:
        return True, raw_abp[:750], raw_ple[:750], best_abp[:750], best_ple[:750], matched_abp_peaks[
            np.argwhere(matched_abp_peaks < 750)], \
            matched_ple_peaks[np.argwhere(matched_ple_peaks < 750)], matched_abp_bottoms[
            np.argwhere(matched_abp_bottoms < 750)], \
            matched_ple_bottoms[np.argwhere(matched_ple_bottoms < 750)], best_corr


def peak_detector(target_signal, rol_sec, fs=125):
    roll_mean = rolling_mean(target_signal, rol_sec, fs)
    peak_heartpy = hp_peak.detect_peaks(target_signal, roll_mean, ma_perc=20, sample_rate=fs)
    return peak_heartpy['peaklist']


def bottom_detector(target_signal, rol_sec, fs=125):
    target_signal = -target_signal
    roll_mean = rolling_mean(target_signal, rol_sec, fs)
    peak_heartpy = hp_peak.detect_peaks(target_signal, roll_mean, ma_perc=20, sample_rate=fs)
    return peak_heartpy['peaklist']


def read_total_data(id: int, segment_list: list, total_patient_info, patient_info_total: list,
                    ple_total: list, abp_total: list, size_total: list, ohe_total: list, chunk_size: int,
                    sampling_rate: int, eliminated_total: list, threshold: float, ple_scale: bool):
    """

    * if a single record is shorter than 6 seconds, skip it to consider only long enough to have respiratory cycles
       else, slice it into 6 seconds segments

    ** if a single record is too long,
        5 consecutive chunks are selected to prevent over-fitting to single record.
        -> it is to include as many patients as possible in datasets


    param:
        path: path of a patient (e.g. /hdd/hdd0/dataset/bpnet/adults/physionet.org/files/mimic3wdb/1.0/30/3001937_11)
        sampfrom: start index of the segment
        sampto: end index of the segment
    return:
        record: wfdb record object containing PLETH and ABP signals
        patient_records: list of wfdb record
    """

    for segment in tqdm(segment_list, desc='process-' + str(id), leave=False):
        chunk_per_segment = 0
        segment = segment.strip('.hea')
        # patient_id = segment.split('/')[-2].split('_')[0]
        patient_id = segment.split('/')[-2].split('_')[0][-5:]
        ple_idx, abp_idx = find_channel_idx(segment)
        ple, abp = np.squeeze(np.split(wfdb.rdrecord(segment, channels=[ple_idx, abp_idx]).p_signal, 2, axis=1))

        """ implement from here"""
        # slice signal by 8 seconds and overlap 2 seconds
        # ensure that the signal length is 8 seconds
        fs = 125
        t = 8
        overlap = 2
        sliced_abp = signal_slicer(abp, fs=fs, t=t, overlap=overlap)
        sliced_ple = signal_slicer(ple, fs=fs, t=t, overlap=overlap)

        # eliminated_total[6] : total number of sliced signals
        if len(sliced_abp) > 0:
            eliminated_total[6] += len(sliced_abp)

        # check if sliced signal is valid
        # if not, remove the signal
        normal_abp = []
        normal_ple = []
        for target_abp, target_ple in zip(sliced_abp, sliced_ple):
            nan_flag_abp, num_nan_abp = nan_checker(target_abp)
            nan_flag_ple, num_nan_ple = nan_checker(target_ple)
            if nan_flag_abp or nan_flag_ple:
                if num_nan_abp < 0.1 * len(target_abp) and num_nan_ple < 0.1 * len(target_ple):
                    target_abp = nan_interpolator(target_abp)
                    target_ple = nan_interpolator(target_ple)
                    # eliminated_total[5] : total number of signals after nan interpolation
                    eliminated_total[5] += 1
                else:
                    # eliminated_total[0] : total number of signals with nan
                    eliminated_total[0] += 1
                    continue
            if flat_signal_checker(target_abp) or flat_signal_checker(target_ple):
                # eliminated_total[1] : total number of signals with flat signal
                eliminated_total[1] += 1
                continue
            else:
                normal_abp.append(target_abp)
                normal_ple.append(target_ple)

        # delete no more needed variables
        # del sliced_abp, sliced_ple

        if len(normal_abp) == 0 or len(normal_ple) == 0:
            continue
        # denoise signal
        # lf = 0.5
        hf = 8
        denoised_abp = [filter_signal(target_abp, cutoff=hf, sample_rate=fs, order=2, filtertype='lowpass') for
                        target_abp in normal_abp]
        denoised_ple = [filter_signal(target_ple, cutoff=hf, sample_rate=fs, order=2, filtertype='lowpass') for
                        target_ple in normal_ple]
        # find peak index
        rolling_sec = 1.5
        peak_abp = [peak_detector(target_abp, rolling_sec, fs) for target_abp in denoised_abp]
        peak_ple = [peak_detector(target_ple, rolling_sec, fs) for target_ple in denoised_ple]
        bottom_abp = [bottom_detector(target_abp, rolling_sec, fs) for target_abp in denoised_abp]
        bottom_ple = [bottom_detector(target_ple, rolling_sec, fs) for target_ple in denoised_ple]

        # arrange peak index
        arranged_peak_abp = []
        arranged_peak_ple = []
        arranged_bottom_abp = []
        arranged_bottom_ple = []
        for target_signal, target_peak, target_bottom in zip(denoised_abp, peak_abp, bottom_abp):
            arranged_peak = sc.SBP_DBP_arranger(target_signal, target_peak, target_bottom)
            arranged_peak_abp.append(arranged_peak[0])
            arranged_bottom_abp.append(arranged_peak[1])

        for target_signal, target_peak, target_bottom in zip(denoised_ple, peak_ple, bottom_ple):
            arranged_peak = sc.SBP_DBP_arranger(target_signal, target_peak, target_bottom)
            arranged_peak_ple.append(arranged_peak[0])
            arranged_bottom_ple.append(arranged_peak[1])

        peak_abp = arranged_peak_abp
        peak_ple = arranged_peak_ple
        bottom_abp = arranged_bottom_abp
        bottom_ple = arranged_bottom_ple

        # delete no more needed variables
        del arranged_peak_abp, arranged_peak_ple, arranged_bottom_abp, arranged_bottom_ple

        # calculate correlation
        # if correlation is less than threshold, remove the signal
        # threshold = 0.9

        for raw_abp, raw_ple, target_abp, target_ple, target_peak_abp, target_peak_ple, target_bottom_abp, target_bottom_ple \
                in zip(normal_abp, normal_ple, denoised_abp, denoised_ple, peak_abp, peak_ple, bottom_abp, bottom_ple):
            # check if peak is valid
            if len(target_peak_abp) == 0 or len(target_peak_ple) == 0:
                # eliminated_total[2] : total number of signals with zero peak
                eliminated_total[2] += 1
                continue
            target_peak_abp = np.array(target_peak_abp)
            target_peak_ple = np.array(target_peak_ple)
            target_bottom_abp = np.array(target_bottom_abp)
            target_bottom_ple = np.array(target_bottom_ple)
            # matching signals then get matched peaks, bottoms and correlation
            match_flag, matched_raw_abp, matched_raw_ple, matched_target_abp, matched_target_ple, matched_abp_peaks, \
                matched_ppg_peaks, matched_abp_bottoms, matched_ple_bottoms, matched_corr = signal_matcher(raw_abp,
                                                                                                           raw_ple,
                                                                                                           target_abp,
                                                                                                           target_ple,
                                                                                                           target_peak_abp,
                                                                                                           target_peak_ple,
                                                                                                           target_bottom_abp,
                                                                                                           target_bottom_ple,
                                                                                                           threshold)
            if match_flag and len(matched_abp_peaks) > 0 and len(matched_abp_bottoms) > 0 \
                    and abs(len(matched_abp_peaks) - len(matched_abp_bottoms)) < 2:
                # plt.plot((matched_raw_abp-np.min(matched_raw_abp))/(np.max(matched_raw_abp)-np.min(matched_raw_abp)), label='raw_abp', c='r')
                # plt.plot((matched_raw_ple-np.min(matched_raw_ple))/(np.max(matched_raw_ple)-np.min(matched_raw_ple)), label='raw_ple', c='b')
                # plt.title('Before downsampling correlation : {:.3f}'.format(matched_corr))
                # plt.legend()
                # plt.show()
                # sampled_abp = matched_raw_abp[15:735:2]
                # sampled_ple = mm.channel_cat(matched_raw_ple)
                sampled_corr = correlation_checker(matched_raw_abp[15:735:2], matched_raw_ple[15:735:2])

                # TODO : edit here
                if sampled_corr < threshold:
                    # eliminated_total[3] : total number of signals with correlation less than threshold
                    eliminated_total[3] += 1
                    continue

                # TODO : raw_ple,abp length need to be modified considering overlap
                if signal_QC:
                    # total : 0 / male : 1 / female : 2
                    # gender, expire_flag = total_patient_info[patient_id]
                    try:
                        p_info = total_patient_info[patient_id][:-1]
                        ohe = total_patient_info[patient_id][-1]
                        # p_info.append(round(matched_corr, 3))
                        patient_info_total.append(np.array(p_info))
                        ohe_total.append(np.array(ohe))
                        ple_total.append(mm.channel_cat(raw_ple[:750], scale=ple_scale))
                        abp_total.append(raw_abp[15:735:2])
                        dbp_mean = np.mean(matched_raw_abp[matched_abp_bottoms])
                        sbp_mean = np.mean(matched_raw_abp[matched_abp_peaks])
                        # sbp_array = np.array([matched_raw_abp[matched_abp_peaks], matched_abp_peaks]).squeeze()
                        size_total.append(np.array([dbp_mean, sbp_mean]))
                        chunk_per_segment += 1
                    except:
                        pass
                    # id, hadm, gender, eth, diag = format(p_info[0], '05'), p_info[1], p_info[2], p_info[3], p_info[4]

                    # patient_set.add(patient_id)
                else:
                    continue

                # plt.plot((sampled_abp-np.min(sampled_abp))/(np.max(sampled_abp)-np.min(sampled_abp)), label='sampled_abp', c='r')
                # plt.plot((sampled_ple-np.min(sampled_ple))/(np.max(sampled_ple)-np.min(sampled_ple)), label='sampled_ple', c='b')
                # plt.title('After downsampling correlation : {:.3f}'.format(sampled_corr))
                # plt.legend()
                # plt.show()
                # ple_total.append(np.array(matched_raw_ple))
                # abp_total.append(np.array(matched_raw_abp))
            else:
                # eliminated_total[3] : total number of signals with low correlation
                eliminated_total[3] += 1
                continue
            if chunk_per_segment == 15:
                # eliminated_total[4] : total number of signals with excess number of signals
                eliminated_total[4] += len(sliced_abp) - 15
                break

        # # check segment length if it is longer than 6 seconds
        # if type(abp) != np.float64 and type(ple) != np.float64 and len(ple) > chunk_size and len(abp) > chunk_size:
        #     # select signal set only longer than 6 seconds, split into 6 seconds chunks
        #     ple_split = np.array_split(ple[:(len(ple) // chunk_size) * chunk_size], len(ple) // chunk_size)
        #     abp_split = np.array_split(abp[:(len(abp) // chunk_size) * chunk_size], len(abp) // chunk_size)
        # else:
        #     continue

        # for p, a in zip(ple_split, abp_split):
        #     flag, mean_dbp, mean_sbp, mean_map = su.signal_respiration_checker(a, p, threshold=0.9)
        #     # flag, mean_dbp, mean_sbp, mean_map = sutemp.signal_slicing(a, p)
        #     if flag:
        #         # ple = down_sampling(p, target_fs=sampling_rate)
        #         ple_total.append(mm.channel_cat(down_sampling(p, target_fs=sampling_rate)))
        #         abp_total.append(down_sampling(a, target_fs=sampling_rate))
        #         size_total.append([mean_dbp, mean_sbp, mean_map])
        #         chunk_per_segment += 1
        #     else:
        #         continue
        #     # else:
        #     #     continue
        #     if chunk_per_segment == 10:
        #         break


def multi_processing(model_name, dset_path: str, dataset: str, total_segments, g_str, total_patient_info, threshold, ple_scale):
    '''
    param:
        model_name: name of model to train (e.g. 'BPNet', 'UNet', 'LSTM'...)
        data_path: path of the dataset (e.g. /hdd/hdd0/dataset/bpnet/adults/physionet.org/files/mimic3wdb/1.0)
    return:
        None
    '''

    if not os.path.exists(dset_path):
        os.mkdir(dset_path)

    print(f'[{model_name} {dataset} dataset]')
    print('dataset name : MIMIC-III')
    print(f'number of segments: {len(total_segments)}')
    print(f'save to: {dset_path}')

    # process_num = get_process_num(len(total_segments))
    # if process_num % 2 != 0:
    #     process_num += 1
    # process_num = 1
    process_num = 48
    print(f'number of processes: {process_num}')
    # processes = []

    ''' Model selection '''
    if model_name == 'BPNet':
        sig_len, samp_rate = 750, 60
    else:
        sig_len, samp_rate = 3000, 300

    ''' Multi-processing '''
    print('sorting data by size... ')
    '''
    size 
    30% 192, 58초 소요 len: 159
    50% 192, 123초 소요
    70% 192, 400초 소요
    80% 192, 905초 소요
    800 : 1
    400 : 3
    300 : 12
    200 : 77
    100 : 470

    '''
    sorted_by_fsize = sorted(total_segments, key=lambda s: os.stat(s.replace('.hea', '.dat')).st_size)

    # light0 = sorted_by_fsize[:int(len(sorted_by_fsize) * 0.25)]  # not used having no valid data
    light1 = sorted_by_fsize[int(len(sorted_by_fsize) * 0.25):int(len(sorted_by_fsize) * 0.4)]
    light2 = sorted_by_fsize[int(len(sorted_by_fsize) * 0.4):int(len(sorted_by_fsize) * 0.55)]
    light3 = sorted_by_fsize[int(len(sorted_by_fsize) * 0.55):int(len(sorted_by_fsize) * 0.7)]  # htop best
    heavy1 = sorted_by_fsize[int(len(sorted_by_fsize) * 0.70):int(len(sorted_by_fsize) * 0.85)]
    heavy2 = sorted_by_fsize[int(len(sorted_by_fsize) * 0.80):int(len(sorted_by_fsize) * 0.95)]
    # heavy3 = sorted_by_fsize[int(len(sorted_by_fsize) * 0.95):] # eliminated due to long time consumption
    # split_by_size = [heavy1] # for real data inspection
    # split_by_size = [light2] # for debugging
    # split_by_size = [light2, light3] # for fast test
    split_by_size = [light1, light2, light3, heavy1, heavy2]  # for total data
    print('reading_total_data...')
    info_tot = np.zeros((1, 5))
    ple_tot = np.zeros((1, 3, 360))
    abp_tot = np.zeros((1, 360))
    size_tot = np.zeros((1, 2))
    ohe_tot = np.zeros((1, 7))
    eliminated_tot = np.zeros((7))
    '''get patient info'''

    for s in split_by_size:
        segments_per_process = np.array_split(s, process_num)
        print(f'number of segments per process: {len(segments_per_process[0])}')
        with mp.Manager() as manager:
            start_time = time.time()

            info_total = manager.list()
            ple_total = manager.list()
            abp_total = manager.list()
            size_total = manager.list()
            ohe_total = manager.list()
            eliminated_total = manager.list()
            eliminated_total.extend([0, 0, 0, 0, 0, 0, 0])
            workers = [mp.Process(target=read_total_data,
                                  args=(i, segments_per_process[i], total_patient_info,
                                        info_total, ple_total, abp_total, size_total, ohe_total,
                                        sig_len, samp_rate, eliminated_total, threshold, ple_scale)) for i in range(process_num)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()

            print('--- %s seconds ---' % (time.time() - start_time))
            # ple_total = np.array(ple_total)
            # abp_total = np.array(abp_total)
            # size_total = np.array(size_total)
            try:
                info_tot = np.concatenate((info_tot, np.array(info_total, dtype=float)), axis=0)
                ple_tot = np.concatenate((ple_tot, np.array(ple_total)), axis=0)
                abp_tot = np.concatenate((abp_tot, np.array(abp_total)), axis=0)
                size_tot = np.concatenate((size_tot, np.array(size_total)), axis=0)
                ohe_tot = np.concatenate((ohe_tot, np.array(ohe_total)), axis=0)
                eliminated_tot = np.array(eliminated_total)
                manager.shutdown()

            except:
                print('no data added')
                manager.shutdown()
                continue

    eliminated_percent = np.zeros(7)
    for i in range(7):
        eliminated_percent[i] = eliminated_tot[i] / eliminated_tot[6] * 100

    print('Eliminated nan signals: {} ({}%)'.format(eliminated_tot[0], eliminated_percent[0]))
    print('Eliminated flat signals: {} ({}%)'.format(eliminated_tot[1], eliminated_percent[1]))
    print('Eliminated signals with no peaks: {} ({}%)'.format(eliminated_tot[2], eliminated_percent[2]))
    print('Eliminated low correlation signals: {} ({}%)'.format(eliminated_tot[3], eliminated_percent[3]))
    print('Eliminated excess chunks: {} ({}%)'.format(eliminated_tot[4], eliminated_percent[4]))
    print('----------------------------------------------')
    print('Interpolated signals: {} ({}%)'.format(eliminated_tot[5], eliminated_percent[5]))
    print('Total sliced signals: {}'.format(eliminated_tot[6]))
    print('Total Eliminated signals: {} ({})%'.format(sum(eliminated_tot[:5]),
                                                      sum(eliminated_tot[:5]) / eliminated_tot[6] * 100))
    print('----------------------------------------------')
    print('Survived total length: {} ({}%)'.format(len(ple_tot), len(ple_tot) / eliminated_tot[6] * 100))
    print(np.shape(ple_tot))
    print(np.shape(abp_tot))
    print(np.shape(size_tot))

    eliminated_tot = np.hstack((eliminated_tot, eliminated_percent))
    dset= h5py.File(dset_path + str(dataset)+'_'+g_str+'_'+str(threshold)+'.hdf5','w')

    # if gender == 0:
    #     dset = h5py.File(dset_path + str(dataset) + '_total_' + str(threshold) + '.hdf5', 'w')
    # elif gender == 1:
    #     dset = h5py.File(dset_path + str(dataset) + '_male_' + str(threshold) + '.hdf5', 'w')
    # else:
    #     dset = h5py.File(dset_path + str(dataset) + '_female_' + str(threshold) + '.hdf5', 'w')

    # ascii_list = [n.encode("ascii", "ignore") for n in info_tot[1:]]
    # data = np.array([['I', 'am', 'a', 'sentence'], ['another', 'sentence']], dtype=object)
    # string_dt = h5py.special_dtype(vlen=str)
    # info_dat = np.array(info_tot[1:], dtype=object)
    # string_dt = h5py.special_dtype(vlen=str)
    # dset.create_dataset('info', data=info_dat, dtype=string_dt)
    # dset.create_dataset('info2', data=np.array(info_dat, dtype='S'))
    # ----- to decode byte to string ------
    # >> str(dset['info'][0][0],'utf-8')
    # ----- to convert ndarray to string type -----
    # dset['info'][0].astype(str)

    # dset['info'] = np.array(info_tot[1:], dtype='str')
    dset['info'] = info_tot[1:]
    dset['ple'] = ple_tot[1:]
    dset['abp'] = abp_tot[1:]
    dset['size'] = size_tot[1:]
    dset['ohe'] = ohe_tot[1:]
    dset['eliminated'] = eliminated_tot
    dset.close()


def dataset_split(model_name: str, data_path: str, g_str: str, threshold: float, ple_scale: bool):
    '''
    gender
    0 : total
    1 : male
    2 : female
    '''
    g_info = gender_info[g_str]
    x = dt.datetime.now()
    date = str(x.year) + str(x.month) + str(x.day)
    if ple_scale:
        dset_path = '/hdd/hdd1/dataset/bpnet/preprocessed_' + date + '_normalized/'
        ssd_path = '/home/paperc/PycharmProjects/dataset/BPNet_mimiciii/additional'+date+'_normalized/'
    else:
        dset_path = '/hdd/hdd1/dataset/bpnet/preprocessed_' + date + '/'
        ssd_path = '/home/paperc/PycharmProjects/dataset/BPNet_mimiciii/additional'+date+'/'
    print('dataset splitting...')
    train_segments, val_segments, test_segments, total_patient_info, patient_df = get_total_segment_path(data_path, gender=g_info[0])
    if not os.path.isdir(dset_path):
        os.mkdir(dset_path)
    patient_df.to_csv(dset_path+'patient_data.csv')

    multi_processing(model_name, dset_path, 'train', train_segments, g_info[-1], total_patient_info, threshold, ple_scale)
    multi_processing(model_name, dset_path, 'val', val_segments, g_info[-1], total_patient_info, threshold, ple_scale)
    multi_processing(model_name, dset_path, 'test', test_segments, g_info[-1], total_patient_info, threshold, ple_scale)
    add_preprocessing.add_preprocess(dset_path, ssd_path, g_info[-1])
    patient_df.to_csv(ssd_path+'patient_data.csv')




# dataset_split('BPNet', '/hdd/hdd1/dataset/bpnet/adults/physionet.org/files/mimic3wdb/1.0')
gen = ["Total"]
# gen = [0, 1, 2]
# gender_list = ["Total", "Male", "Female"]
scale = [True, False]
for s in scale:
    for g in gen:
        dataset_split('BPNet', '/hdd/hdd1/dataset/mimiciiisubset/physionet.org/files/mimic3wdb-matched/1.0', g_str=g, threshold=0.9, ple_scale=s)
