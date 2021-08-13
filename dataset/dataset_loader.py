import h5py
import numpy as np
import os

from dataset.DeepPhysDataset import DeepPhysDataset
from dataset.PhysNetDataset import PhysNetDataset
from dataset.MetaPhysDataset import MetaPhysDataset

def dataset_loader(save_root_path: str = "/media/hdd1/dy_dataset/",
                   model_name: str = "DeepPhys",
                   dataset_name: str = "UBFC",
                   option: str = "train",

                   num_shots: int = 6,
                   num_test_shots:int =2,
                   fs: int = 30,
                   unsupervised: int = 0
                   ):
    '''
    :param save_root_path: save file destination path
    :param model_name : model_name
    :param dataset_name: data set name(ex. UBFC, COFACE)
    :param option:[train, test]
    :return: dataset
    '''
    hpy_file = h5py.File(save_root_path + model_name + "_" + dataset_name + "_" + option + ".hdf5", "r")

    if model_name == "DeepPhys":
        appearance_data = []
        motion_data = []
        target_data = []

        for key in hpy_file.keys():
            appearance_data.extend(hpy_file[key]['preprocessed_video'][:, :, :, -3:])
            motion_data.extend(hpy_file[key]['preprocessed_video'][:, :, :, :3])
            target_data.extend(hpy_file[key]['preprocessed_label'])
        hpy_file.close()
        dataset = DeepPhysDataset(appearance_data=np.asarray(appearance_data),
                                  motion_data=np.asarray(motion_data),
                                  target=np.asarray(target_data))
    elif model_name == "PhysNet" or model_name == "PhysNet_LSTM":
        video_data = []
        label_data = []
        for key in hpy_file.keys():
            video_data.extend(hpy_file[key]['preprocessed_video'])
            label_data.extend(hpy_file[key]['preprocessed_label'])
        hpy_file.close()

        dataset = PhysNetDataset(video_data=np.asarray(video_data),
                                 label_data=np.asarray(label_data))

    if model_name == "MetaPhys":
        appearance_data = []
        motion_data = []
        target_data = []

        for key in hpy_file.keys(): #subject1, subject10, ...
            appearance_data.append(hpy_file[key]['preprocessed_video'][:, :, :, -3:])
            motion_data.append(hpy_file[key]['preprocessed_video'][:, :, :, :3])
            target_data.append(hpy_file[key]['preprocessed_label'][:])
        hpy_file.close()

        dataset = MetaPhysDataset(num_shots,
                                  num_test_shots,
                                  option,
                                  fs,
                                  unsupervised,
                                  frame_depth=10,

                                  appearance_data=np.asarray(appearance_data),
                                  motion_data=np.asarray(motion_data),
                                  target=np.asarray(target_data)
                                  )

    return dataset
