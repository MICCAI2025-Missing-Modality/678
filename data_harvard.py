import numpy as np
import scipy.io as sio
from torch.utils.data import Dataset
# from sklearn.preprocessing import MinMaxScaler
from os.path import join
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
from PIL import Image
import os
import sys
import argparse
import time
import math
import pandas as pd
from sklearn.model_selection import KFold
import cv2
from torchvision import transforms
from scipy import ndimage
import nibabel as nib



def add_salt_peper_3D(image,amout):
    s_vs_p = 0.5
    noisy_img = np.copy(image)
    num_salt = np.ceil(amout * image.size * s_vs_p)
    coords = [np.random.randint(0, i - 1, int(num_salt)) for i in image.shape]
    noisy_img[coords[0], coords[1]] = 1.
    num_pepper = np.ceil(amout * image.size * (1. - s_vs_p))
    coords = [np.random.randint(0, i - 1, int(num_pepper)) for i in image.shape]
    noisy_img[coords[0], coords[1]] = 0.
    return noisy_img

def add_salt_peper(image,amout):
    s_vs_p = 0.5
    noisy_img = np.copy(image)

    num_salt = np.ceil(amout * image.shape[0] * image.shape[1] * s_vs_p)

    coords = [np.random.randint(0, i - 1, int(num_salt)) for i in image.shape]
    noisy_img[coords[0], coords[1], :] = 1.

    num_pepper = np.ceil(amout * image.shape[0] * image.shape[1] * (1. - s_vs_p))

    coords = [np.random.randint(0, i - 1, int(num_pepper)) for i in image.shape]
    noisy_img[coords[0], coords[1], :] = 0.
    return noisy_img

class GAMMA_sub1_dataset(Dataset):
    def __init__(self,
                 dataset_root,
                 oct_img_size,
                 fundus_img_size,
                 mode='train',
                 label_file='',
                 filelists=None,
                 ):

        self.dataset_root = dataset_root
        self.input_D = oct_img_size[0][0]
        self.input_H = oct_img_size[0][1]
        self.input_W = oct_img_size[0][2]
        mean = (0.3163843, 0.86174834, 0.3641431)
        std = (0.24608557, 0.11123227, 0.26710403)
        normalize = transforms.Normalize(mean=mean, std=std)

        self.fundus_train_transforms = transforms.Compose([
            transforms.ToTensor(),
            transforms.RandomApply([
                transforms.ColorJitter(0.2, 0.2, 0.2, 0.1)
            ], p=0.8),
            transforms.RandomGrayscale(p=0.2),
            transforms.CenterCrop(600),
            transforms.Resize(fundus_img_size[0][0]),
            transforms.RandomHorizontalFlip(),
            normalize,
        ])

        self.oct_train_transforms = transforms.Compose([
            transforms.ToTensor(),
            transforms.RandomHorizontalFlip(),
        ])

        self.fundus_val_transforms = transforms.Compose([
            transforms.ToTensor(),
            transforms.Resize(fundus_img_size[0][0])
        ])

        self.oct_val_transforms = transforms.Compose([
            transforms.ToTensor(),
        ])

        self.mode = mode.lower()
        label = {row['data']: row[1:].values
            for _, row in pd.read_excel(label_file).iterrows()}
        # if train is all
        self.file_list = []
        for f in filelists:
            self.file_list.append([f, label[int(f)]])

        # if only for test
        # if self.mode == 'train':
        #     label = {row['data']: row[1:].values
        #              for _, row in pd.read_excel(label_file).iterrows()}
        #
        #     self.file_list = [[f, label[int(f)]] for f in os.listdir(dataset_root)]
        # elif self.mode == "test" or self.mode == "val" :
        #     self.file_list = [[f, None] for f in os.listdir(dataset_root)]

        # if filelists is not None:
        #     self.file_list = [item for item in self.file_list if item[0] in filelists]
    def __getitem__(self, idx):
        data = dict()

        real_index, label = self.file_list[idx]

        # Fundus read
        fundus_img_path = os.path.join(self.dataset_root, real_index,real_index +".png")
        fundus_img = cv2.imread(fundus_img_path)[:, :, ::-1]  # BGR -> RGB
        # OCT read
        # oct_series_list = sorted(os.listdir(os.path.join(self.dataset_root, real_index, real_index)),
        #                             key=lambda x: int(x.strip("_")[0]))
        oct_series_list = os.listdir(os.path.join(self.dataset_root, real_index, real_index))
        oct_series_0 = cv2.imread(os.path.join(self.dataset_root, real_index, real_index, oct_series_list[0]),
                                  cv2.IMREAD_GRAYSCALE)
        oct_img = np.zeros((len(oct_series_list), oct_series_0.shape[0], oct_series_0.shape[1], 1), dtype="uint8")
        for k, p in enumerate(oct_series_list):
            oct_img[k] = cv2.imread(
                os.path.join(self.dataset_root, real_index, real_index, p), cv2.IMREAD_GRAYSCALE)[..., np.newaxis]

        # Fundus clip
        if fundus_img.shape[0] == 2000:
            fundus_img = fundus_img[1000 - 967:1000 + 967, 1496 - 978:1496 + 978, :]

        fundus_img = fundus_img.copy()
        oct_img = self.__resize_oct_data__(oct_img)
        fundus_img = fundus_img / 255.0
        oct_img = oct_img / 255.0
        if self.mode == "train":
            fundus_img = self.fundus_train_transforms(fundus_img.astype(np.float32))
            oct_img = self.oct_train_transforms(oct_img.astype(np.float32))
        else:
            fundus_img = self.fundus_val_transforms(fundus_img)
            oct_img = self.oct_val_transforms(oct_img)
        # data[0] = fundus_img.transpose(2, 0, 1) # H, W, C -> C, H, W
        # data[1] = oct_img.squeeze(-1) # D, H, W, 1 -> D, H, W
        data[0] = fundus_img
        data[1] = oct_img.unsqueeze(0)

        label = label.argmax()

        return data, label

    def __len__(self):
        return len(self.file_list)

    def __resize_oct_data__(self, data):
        """
        Resize the data to the input size
        """
        data = data.squeeze()
        [depth, height, width] = data.shape
        scale = [self.input_D*1.0/depth, self.input_H *1.0/height, self.input_W*1.0/width]
        data = ndimage.interpolation.zoom(data, scale, order=0)
        # data = data.unsqueeze()
        return data
    
def scale_image(image, patch_size):
    image = cv2.resize(image, (patch_size, patch_size), interpolation=cv2.INTER_CUBIC)
    return image
    
def resize_oct_data_trans(data, size):
    """
    Resize the data to the input size
    """
    input_D, input_H, input_W = size[0],size[1],size[2]
    data = data.squeeze()
    [depth, height, width] = data.shape
    scale = [input_D*1.0/depth, input_H *1.0/height, input_W*1.0/width]
    data = ndimage.interpolation.zoom(data, scale, order=0)
    # data = data.unsqueeze()
    return data

# class OLIVES_dataset(Dataset):
#     """
#     load multi-view data
#     """
#
#     def __init__(self, root, modal_number,modalties,mode,condition,args, folder='folder0'):
#         """
#         :param root: data name and path
#         :param train: load training set or test set
#         """
#         super(OLIVES_dataset, self).__init__()
#         self.root = root
#         self.mode = mode
#         self.data_path = self.root + folder + "/"
#         self.modalties = modalties
#         self.condition = condition
#         self.condition_name = args.condition_name
#         self.seed_idx = args.seed_idx
#         self.Condition_SP_Variance = args.Condition_SP_Variance
#         self.Condition_G_Variance = args.Condition_G_Variance
#         self.model_base = args.model_base
#
#         y_files = []
#
#         self.X = dict()
#         for m_num in range(modal_number):
#             x_files = []
#             c_m = modalties[m_num]
#             with open(join(self.data_path, self.mode +"_" + c_m + '.txt'),
#                           'r',encoding="gb18030",errors="ignore") as fx:
#                 files = fx.readlines()
#                 for file in files:
#                     file = file.replace('\n', '')
#                     x_files.append(file)
#                 self.X[m_num] = x_files
#         with open(join(self.data_path, self.mode + '_GT.txt'),
#                           'r') as fy:
#             yfiles = fy.readlines()
#             for yfile in yfiles:
#                 yfile = yfile.replace('\n', '')
#                 y_files.append(yfile)
#         self.y = y_files
#
#     def __getitem__(self, file_num):
#         data = dict()
#         np.random.seed(self.seed_idx)
#         for m_num in range(len(self.X)):
#             self.X[m_num][file_num] = self.X[m_num][file_num].replace('/home/','/data/')
#             if self.modalties[m_num] == "FUN":
#                 fundus_data = np.load(self.X[m_num][file_num]).astype(np.float32)
#                 # first
#                 # data_PIL = Image.fromarray(fundus_data/255.0)
#                 # data_PIL = data_PIL.convert("RGB")
#                 # np_data = np.array(data_PIL).transpose((2, 1, 0))
#                 # data[m_num] = np_data
#
#                 # right
#                 data_PIL = Image.fromarray(fundus_data)
#                 data_PIL = data_PIL.convert("RGB")
#                 np_data = np.array(data_PIL).transpose((2, 1, 0))#  H * W * 3 - > 3 * W * H
#                 if self.model_base == "transformer":
#                     np_data = scale_image(np_data.transpose(1,2,0), 384)
#                     data[m_num] = np_data.transpose(2,0,1)/255.0 # H * W * 3 - > 3 * W * H
#                 else:
#                     data[m_num] = np_data/255.0 # H * W * 3 - > 3 * W * H
#
#                 # resize to 256*256
#                 # np_km = np.load(self.X[m_num][file_num]).astype(np.float32)
#                 # Image_km = Image.fromarray(np.uint8(np_km.transpose(1, 2, 0)))
#                 # resize_km = Image_km.resize((256,256))
#                 # data[m_num] = np.array(resize_km).transpose(2, 1, 0).astype(np.float32)
#                 # plt.figure(5)
#                 # # plt.imshow(data[m_num].transpose(1,2,0).astype(np.uint8))
#                 # plt.imshow(data[m_num].transpose(1,2,0))
#                 # plt.axis('off')
#                 # plt.show()
#                 noise_data = data[m_num].copy()
#
#                 # ## Noise begin
#                 # if self.condition == 'noise':
#                 #     if self.condition_name == "SaltPepper":
#                 #         # data[m_num] = addsalt_pepper(data[m_num], self.Condition_SP_Variance)  # c,
#                 #         noise_data = add_salt_peper(noise_data.transpose(1, 2, 0), self.Condition_SP_Variance)  # c,
#                 #         noise_data = noise_data.transpose(2, 0, 1)
#                 #     # data[m_num] = data[m_num] + noise_data.astype(np.float32)
#                 #     # data[m_num] = data[m_num]
#                 #     elif self.condition_name == "Gaussian":
#
#                 #         noise_add = np.random.normal(0, self.Condition_G_Variance, noise_data.shape)
#                 #         # noise_add = np.random.random(noise_data.shape) * self.Condition_G_Variance
#
#                 #         # add noise
#                 #         # noise_data = noise_data + noise_add
#
#                 #         # add zero
#                 #         noise_data = np.zeros_like(noise_data)
#
#                 #         noise_data = np.clip(noise_data, 0.0, 1.0)
#
#                 #     else:
#                 #         # noise_add = np.random.random(noise_data.shape) * self.Condition_G_Variance
#                 #         noise_add = np.random.normal(0, self.Condition_G_Variance, noise_data.shape)
#                 #         noise_data = noise_data + noise_add
#                 #         noise_data = np.clip(noise_data, 0.0, 1.0)
#                 #         noise_data = add_salt_peper(noise_data, self.Condition_SP_Variance)  # c,
#                 #     data[m_num] = noise_data
#                 # noise end
#                     ## plt.figure(6)
#                     ## plt.imshow(noise_data.transpose(1, 2, 0))
#                     ## plt.axis('off')
#                     ## plt.show()
#                 data[m_num] = noise_data.astype(np.float32)
#                 ## Noise end
#
#             else:
#                 kk = np.load(self.X[m_num][file_num]).astype(np.float32)
#                 if self.model_base == "transformer":
#                     kk = resize_oct_data_trans(kk,(96,96,96))
#                 kk = kk / 255.0
#                 # kk = np.load(self.X[m_num][file_num])
#                 noise_kk = kk.copy()
#                 # plt.figure(1)
#                 # plt.imshow(kk[0, :, :], cmap="gray")
#                 # plt.axis('off')
#                 # plt.show()
#                 # plt.figure(2)
#                 # plt.imshow(kk[127, :, :], cmap="gray")
#                 # plt.axis('off')
#                 # plt.show()
#
#                 # Noise begin
#                 if self.condition == 'noise':
#                     ## plt.figure(1)
#                     ## PIL_kk = Image.fromarray(kk[60,:,:])
#                     ## plt.imshow(PIL_kk)
#                     ## plt.show()
#                     if self.condition_name == "SaltPepper":
#                         for i in range(kk.shape[0]):
#                             noise_kk[i,:,:] = add_salt_peper_3D(kk[i,:,:], self.Condition_SP_Variance)  # c,
#
#                     elif self.condition_name == "Gaussian":
#                         # noise_data = np.random.random(kk.shape) * self.Condition_G_Variance
#                         noise_add = np.random.normal(0, self.Condition_G_Variance, kk.shape)
#                         # noise_kk = kk + noise_data.astype(np.float32)
#
#                         # add noise
#                         # noise_kk = noise_kk + noise_add
#
#                         # add zero
#                         noise_kk = np.zeros_like(kk)
#
#
#                         # if noise_kk.min() < 0:
#                         #     low_clip = -1.
#                         # else:
#                         #     low_clip = 0.
#                         noise_kk = np.clip(noise_kk, 0.0, 1.0)
#                     else:
#                         noise_add = np.random.normal(0, self.Condition_G_Variance, kk.shape)
#                         # noise_kk = kk + noise_data.astype(np.float32)
#                         noise_kk = noise_kk + noise_add
#                         for i in range(kk.shape[0]):
#                             noise_kk[i,:,:] = add_salt_peper_3D(kk[i,:,:], self.Condition_SP_Variance)  # c,
#                     # Noise End
#
#                     # plt.figure(3)
#                     # plt.imshow(noise_kk[0, :, :], cmap="gray")
#                     # plt.axis('off')
#                     # plt.show()
#                     # plt.figure(4)
#                     # plt.imshow(noise_kk[127, :, :], cmap="gray")
#                     # plt.axis('off')
#                     # plt.show()
#                 data[m_num] = np.expand_dims(noise_kk.astype(np.float32), axis=0)
#                 # data[m_num] = np.expand_dims(kk, axis=0)
#                 # data[m_num] = self.__itensity_normalize_one_volume__(data[m_num])
#                 # data[m_num] = data[m_num] / 255.0
#                 # plt.figure(2)
#                 # PIL_noise = Image.fromarray(data[m_num][0, 60,:,:])
#                 # plt.imshow(PIL_noise)
#                 # plt.show()
#
#         # plt.figure(1)
#         # plt.imshow(data[0].transpose(1,2,0))
#         # plt.show()
#         # plt.figure(2)
#         # plt.imshow(data[1][60,:,:].transpose(1,2,0))
#         # plt.show()
#         target_y = int(self.y[file_num])
#         target_y = np.array(target_y)
#         target =  torch.from_numpy(target_y)
#         return data, target
#
#     def __itensity_normalize_one_volume__(self, volume):
#         """
#         normalize the itensity of an nd volume based on the mean and std of nonzeor region
#         inputs:
#             volume: the input nd volume
#         outputs:
#             out: the normalized nd volume
#         """
#
#         pixels = volume[volume > 0]
#         mean = pixels.mean()
#         std = pixels.std()
#         out = (volume - mean) / std
#         out_random = np.random.normal(0, 1, size=volume.shape)
#         out[volume == 0] = out_random[volume == 0]
#         return out
#
#     def __len__(self):
#         return len(self.X[0])
#
# class Multi_modal_data(Dataset):
#     """
#     load multi-view data
#     """
#
#     def __init__(self, root, modal_number,modalties,mode,condition,args, folder='folder0'):
#         """
#         :param root: data name and path
#         :param train: load training set or test set
#         """
#         super(Multi_modal_data, self).__init__()
#         self.root = root
#         self.mode = mode
#         self.data_path = self.root + folder + "/"
#         self.modalties = modalties
#         self.condition = condition
#         self.dataset = args.dataset
#         self.condition_name = args.condition_name
#         self.seed_idx = args.seed_idx
#         self.Condition_SP_Variance = args.Condition_SP_Variance
#         self.Condition_G_Variance = args.Condition_G_Variance
#         self.model_base = args.model_base
#
#         y_files = []
#
#         self.X = dict()
#         for m_num in range(modal_number):
#             x_files = []
#             c_m = modalties[m_num]
#             with open(join(self.data_path, self.mode +"_" + c_m + '.txt'),
#                           'r',encoding="gb18030",errors="ignore") as fx:
#                 files = fx.readlines()
#                 for file in files:
#                     file = file.replace('\n', '')
#                     x_files.append(file)
#                 self.X[m_num] =x_files
#         with open(join(self.data_path, self.mode + '_GT.txt'),
#                           'r') as fy:
#             yfiles = fy.readlines()
#             for yfile in yfiles:
#                 yfile = yfile.replace('\n', '')
#                 y_files.append(yfile)
#         self.y = y_files
#
#     def __getitem__(self, file_num):
#         data = dict()
#         np.random.seed(self.seed_idx)
#         for m_num in range(len(self.X)):
#             num_data_path = self.X[m_num][file_num]
#             if self.dataset == 'MMOCTF':
#                 num_data_path = num_data_path.replace('E:/dataset/', '/data/zou_ke/projects_data/')
#             if self.modalties[m_num] == "FUN":
#                 data[m_num] = np.load(num_data_path).astype(np.float32)
#                 # plt.figure(4)
#                 # plt.imshow(data[m_num].transpose(1,2,0).astype(np.uint8))
#                 # plt.axis('off')
#                 # plt.show()
#                 if self.model_base == "transformer":
#                     data[m_num] = scale_image(data[m_num].transpose(1,2,0), 384) #  H * W * 3
#                     data[m_num] = data[m_num].transpose(2,0,1)/255.0 # 3 * H * W
#                 else:
#                     data[m_num] = data[m_num]/255.0
#
#                 # resize to 256*256
#                 # np_km = np.load(self.X[m_num][file_num]).astype(np.float32)
#                 # Image_km = Image.fromarray(np.uint8(np_km.transpose(1, 2, 0)))
#                 # resize_km = Image_km.resize((256,256))
#                 # data[m_num] = np.array(resize_km).transpose(2, 1, 0).astype(np.float32)
#                 # plt.figure(5)
#                 # plt.imshow(data[m_num].transpose(1,2,0))
#                 # plt.axis('off')
#                 # plt.show()
#                 noise_data = data[m_num].copy()
#                 if self.condition == 'noise':
#                     if self.condition_name == "SaltPepper":
#                         # data[m_num] = addsalt_pepper(data[m_num], self.Condition_SP_Variance)  # c,
#                         noise_data = add_salt_peper(noise_data.transpose(1, 2, 0), self.Condition_SP_Variance)  # c,
#                         noise_data = noise_data.transpose(2, 0, 1)
#                     # data[m_num] = data[m_num] + noise_data.astype(np.float32)
#                     # data[m_num] = data[m_num]
#                     elif self.condition_name == "Gaussian":
#
#                         noise_add = np.random.normal(0, self.Condition_G_Variance, noise_data.shape)
#                         # noise_add = np.random.random(noise_data.shape) * self.Condition_G_Variance
#                         # add noise
#                         # noise_data = noise_data + noise_add
#                         # add zero
#                         noise_data = np.zeros_like(noise_data)
#                         noise_data = np.clip(noise_data, 0.0, 1.0)
#
#                     else:
#                         # noise_add = np.random.random(noise_data.shape) * self.Condition_G_Variance
#                         noise_add = np.random.normal(0, self.Condition_G_Variance, noise_data.shape)
#                         noise_data = noise_data + noise_add
#                         noise_data = np.clip(noise_data, 0.0, 1.0)
#                         noise_data = add_salt_peper(noise_data, self.Condition_SP_Variance)  # c,
#                     # data[m_num] = noise_data
#                     # plt.figure(6)
#                     # plt.imshow(noise_data.transpose(1, 2, 0))
#                     # plt.axis('off')
#                     # plt.show()
#                 data[m_num] = noise_data.astype(np.float32)
#
#             else:
#                 kk = np.load(num_data_path).astype(np.float32)
#                 if self.model_base == "transformer":
#                     kk = resize_oct_data_trans(kk,(96,96,96))
#                 # plt.figure(1)
#                 # plt.imshow(kk[0, :, :], cmap="gray")
#                 # plt.axis('off')
#                 # plt.show()
#                 # plt.figure(2)
#                 # plt.imshow(kk[127, :, :], cmap="gray")
#                 # plt.axis('off')
#                 # plt.show()
#                 kk = kk / 255.0
#                 # kk = np.load(self.X[m_num][file_num])
#                 noise_kk = kk.copy()
#                 # plt.figure(3)
#                 # plt.imshow(kk[0, :, :], cmap="gray")
#                 # plt.axis('off')
#                 # plt.show()
#                 # plt.figure(4)
#                 # plt.imshow(kk[127, :, :], cmap="gray")
#                 # plt.axis('off')
#                 # plt.show()
#                 # if self.condition == 'noise':
#                 #     ## plt.figure(1)
#                 #     ## PIL_kk = Image.fromarray(kk[60,:,:])
#                 #     ## plt.imshow(PIL_kk)
#                 #     ## plt.show()
#                 #     if self.condition_name == "SaltPepper":
#                 #         for i in range(kk.shape[0]):
#                 #             noise_kk[i,:,:] = add_salt_peper_3D(kk[i,:,:], self.Condition_SP_Variance)  # c,
#
#                 #     elif self.condition_name == "Gaussian":
#                 #         # noise_data = np.random.random(kk.shape) * self.Condition_G_Variance
#                 #         noise_add = np.random.normal(0, self.Condition_G_Variance, kk.shape)
#                 #         # noise_kk = kk + noise_data.astype(np.float32)
#
#                 #         # noise add
#                 #         # noise_kk = noise_kk + noise_add
#                 #         # add zero
#                 #         noise_kk = np.zeros_like(kk)
#
#                 #         # if noise_kk.min() < 0:
#                 #         #     low_clip = -1.
#                 #         # else:
#                 #         #     low_clip = 0.
#                 #         noise_kk = np.clip(noise_kk, 0.0, 1.0)
#                 #     else:
#                 #         noise_add = np.random.normal(0, self.Condition_G_Variance, kk.shape)
#                 #         # noise_kk = kk + noise_data.astype(np.float32)
#                 #         noise_kk = noise_kk + noise_add
#                 #         for i in range(kk.shape[0]):
#                 #             noise_kk[i,:,:] = add_salt_peper_3D(kk[i,:,:], self.Condition_SP_Variance)  # c,
#                     # plt.figure(1)
#                     # plt.imshow(noise_kk[0, :, :], cmap="gray")
#                     # plt.axis('off')
#                     # plt.show()
#                     # plt.figure(2)
#                     # plt.imshow(noise_kk[127, :, :], cmap="gray")
#                     # plt.axis('off')
#                     # plt.show()
#                 data[m_num] = np.expand_dims(noise_kk.astype(np.float32), axis=0)
#                 # data[m_num] = np.expand_dims(kk, axis=0)
#                 # data[m_num] = self.__itensity_normalize_one_volume__(data[m_num])
#                 # data[m_num] = data[m_num] / 255.0
#                 # plt.figure(2)
#                 # PIL_noise = Image.fromarray(data[m_num][0, 60,:,:])
#                 # plt.imshow(PIL_noise)
#                 # plt.show()
#
#
#         target_y = int(self.y[file_num])
#         target_y = np.array(target_y)
#         target =  torch.from_numpy(target_y)
#         return data, target
#
#     def __itensity_normalize_one_volume__(self, volume):
#         """
#         normalize the itensity of an nd volume based on the mean and std of nonzeor region
#         inputs:
#             volume: the input nd volume
#         outputs:
#             out: the normalized nd volume
#         """
#
#         pixels = volume[volume > 0]
#         mean = pixels.mean()
#         std = pixels.std()
#         out = (volume - mean) / std
#         out_random = np.random.normal(0, 1, size=volume.shape)
#         out[volume == 0] = out_random[volume == 0]
#         return out
#
#     def __len__(self):
#         return len(self.X[0])
#

class GAMMA_dataset(Dataset):
    def __init__(self,
                 args,
                 dataset_root,
                 oct_img_size,
                 fundus_img_size,
                 mode='train',
                 label_file='',
                 filelists=None,
                 ):
        self.condition = args.condition
        self.condition_name = args.condition_name
        self.Condition_SP_Variance = args.Condition_SP_Variance
        self.Condition_G_Variance = args.Condition_G_Variance
        self.seed_idx = args.seed_idx
        self.model_base = args.model_base

        self.dataset_root = dataset_root
        self.input_D = oct_img_size[0][0]
        self.input_H = oct_img_size[0][1]
        self.input_W = oct_img_size[0][2]


        self.fundus_train_transforms = transforms.Compose([
            transforms.ToTensor(),
            transforms.RandomApply([
                transforms.ColorJitter(0.2, 0.2, 0.2, 0.1)
            ], p=0.8),
            transforms.RandomGrayscale(p=0.2),
            transforms.RandomHorizontalFlip(),

        ])

        self.oct_train_transforms = transforms.Compose([
            transforms.ToTensor(),
            transforms.RandomHorizontalFlip(),
        ])

        self.fundus_val_transforms = transforms.Compose([
            transforms.ToTensor(),
        ])

        self.oct_val_transforms = transforms.Compose([
            transforms.ToTensor(),
        ])

        self.mode = mode.lower()
        label = {row['data']: row[1:].values
            for _, row in pd.read_excel(label_file).iterrows()}


        self.file_list = []
        for f in filelists:
            filename = os.path.basename(f)
            if filename.isdigit():
                self.file_list.append([f, label[int(filename)]])


    def __getitem__(self, idx):
        data_low = dict()
        data_high = dict()

        real_index, label = self.file_list[idx]

        # 构建基金图像路径并读取图像
        fundus_img_path = os.path.join(
            self.dataset_root.replace('/MGamma/', '/multi-modality_images/'), 
            real_index, 
            f"data_{real_index}_fundus.png"
        )
        fundus_img = cv2.imread(fundus_img_path)

        # 尝试加载原始 NIfTI 文件，如果不存在则加载处理后的文件
        try:
            nii_path = os.path.join(self.dataset_root, real_index, f"data_{real_index}.nii")
            if not os.path.exists(nii_path):
                raise FileNotFoundError(f"File not found: {nii_path}")
        except FileNotFoundError:
            nii_path = os.path.join(self.dataset_root, real_index, f"processed_data_{real_index}.nii")
        
        nii_data = nib.load(nii_path)
        oct_img = nii_data.get_fdata()
        oct_img = np.array(oct_img, dtype=np.float32)
        oct_img = np.transpose(oct_img, (2, 0, 1))  # 转置为 (D, H, W)
        #print(oct_img.shape) # (200, 256, 256)


        # 图像缩放
        if self.model_base == "transformer":
            fundus_img = scale_image(fundus_img, 384)
            oct_img = resize_oct_data_trans(oct_img, (96, 96, 96))
        else:
            fundus_img = scale_image(fundus_img, 512)
            oct_img = self.__resize_oct_data__(oct_img)

        # 归一化
        oct_img = oct_img / 255.0
        fundus_img = fundus_img / 255.0

        # 设置随机种子
        np.random.seed(self.seed_idx)

        # 定义低噪声和高噪声的参数（根据需要调整这些参数）
        if self.condition == 'noise':
            # 低噪声
            if self.condition_name == "SaltPepper":
                fundus_img_low = add_salt_peper(
                    fundus_img.transpose(1, 2, 0), 
                    self.Condition_SP_Variance_low
                ).transpose(2, 0, 1)
                oct_img_low = np.copy(oct_img)
                for i in range(oct_img_low.shape[0]):
                    oct_img_low[i, :, :] = add_salt_peper_3D(
                        oct_img_low[i, :, :], 
                        self.Condition_SP_Variance_low
                    )
            
            elif self.condition_name == "Gaussian":
                noise_add_low = np.random.normal(0,0, oct_img.shape)
                #noise_add_low = np.random.normal(0, self.Condition_G_Variance, oct_img.shape)
                oct_img_low = np.clip(oct_img + noise_add_low, 0.0, 1.0)
                oct_img_low = oct_img_low
                # oct_img_low =   oct_img_low
                
                
                fundus_img_low = fundus_img  # 如果仅对 OCT 添加高斯噪声，可以保持 fundus_img 不变
                # 如果也需要对 fundus_img 添加噪声，请取消注释以下代码
                #noise_add_low_fundus = np.random.normal(0, self.Condition_G_Variance, fundus_img.shape)
                noise_add_low_fundus = np.random.normal(0, 0 , fundus_img.shape)
                fundus_img_low = np.clip(fundus_img + noise_add_low_fundus, 0.0, 1.0)
                fundus_img_low =  fundus_img_low #25/01/24 18: 15
            
            else:
                # 其他噪声类型，假设同时对 fundus 和 OCT 添加高斯和盐椒噪声
                # 低噪声
                noise_add_low_fundus = np.random.normal(
                    0, 
                    self.Condition_G_Variance_low, 
                    fundus_img.shape
                )
                fundus_img_low = np.clip(fundus_img + noise_add_low_fundus, 0.0, 1.0)
                fundus_img_low = add_salt_peper(
                    fundus_img_low, 
                    self.Condition_SP_Variance_low
                )
                
                noise_add_low_oct = np.random.normal(
                    0, 
                    self.Condition_G_Variance, 
                    oct_img.shape
                )
                oct_img_low = np.clip(oct_img + noise_add_low_oct, 0.0, 1.0)
                for i in range(oct_img_low.shape[0]):
                    oct_img_low[i, :, :] = add_salt_peper_3D(
                        oct_img_low[i, :, :], 
                        self.Condition_SP_Variance_low
                    )
            
            # 高噪声
            if self.condition_name == "SaltPepper":
                fundus_img_high = add_salt_peper(
                    fundus_img.transpose(1, 2, 0), 
                    self.Condition_SP_Variance_high
                ).transpose(2, 0, 1)
                oct_img_high = np.copy(oct_img)
                for i in range(oct_img_high.shape[0]):
                    oct_img_high[i, :, :] = add_salt_peper_3D(
                        oct_img_high[i, :, :], 
                        self.Condition_SP_Variance_high
                    )
            
            elif self.condition_name == "Gaussian":
                noise_add_high = np.random.normal(
                    0, 
                    0.5, 
                    oct_img.shape
                )
                oct_img_high = np.clip(oct_img + noise_add_high, 0.0, 1.0)
                #fundus_img_high = fundus_img  # 如果仅对 OCT 添加高斯噪声，可以保持 fundus_img 不变
                # 如果也需要对 fundus_img 添加噪声，请取消注释以下代码
                noise_add_high_fundus = np.random.normal(
                    0, 
                    0.5, 
                    fundus_img.shape
                )
                fundus_img_high = np.clip(fundus_img + noise_add_high_fundus, 0.0, 1.0)
            
            else:
                # 其他噪声类型，假设同时对 fundus 和 OCT 添加高斯和盐椒噪声
                # 高噪声
                noise_add_high_fundus = np.random.normal(
                    0, 
                    self.Condition_G_Variance_high, 
                    fundus_img.shape
                )
                fundus_img_high = np.clip(fundus_img + noise_add_high_fundus, 0.0, 1.0)
                fundus_img_high = add_salt_peper(
                    fundus_img_high, 
                    self.Condition_SP_Variance_high
                )
                
                noise_add_high_oct = np.random.normal(
                    0, 
                    self.Condition_G_Variance_high, 
                    oct_img.shape
                )
                oct_img_high = np.clip(oct_img + noise_add_high_oct, 0.0, 1.0)
                for i in range(oct_img_high.shape[0]):
                    oct_img_high[i, :, :] = add_salt_peper_3D(
                        oct_img_high[i, :, :], 
                        self.Condition_SP_Variance_high
                    )

        else:
            # 如果没有添加噪声的需求，直接复制原始图像
            fundus_img_low = fundus_img_high = fundus_img
            oct_img_low = oct_img_high = oct_img

        # 应用数据增强和转换
        if self.mode == "train":
            fundus_img_low = self.fundus_train_transforms(fundus_img_low.astype(np.float32))
            oct_img_low = self.oct_train_transforms(oct_img_low.astype(np.float32))
            
            fundus_img_high = self.fundus_train_transforms(fundus_img_high.astype(np.float32))
            oct_img_high = self.oct_train_transforms(oct_img_high.astype(np.float32))
        else:
            fundus_img_low = self.fundus_val_transforms(fundus_img_low)
            oct_img_low = self.oct_val_transforms(oct_img_low)
            
            fundus_img_high = self.fundus_val_transforms(fundus_img_high)
            oct_img_high = self.oct_val_transforms(oct_img_high)

        # 组织数据
        data_low[0] = fundus_img_low
        data_low[1] =  oct_img_low.unsqueeze(0)

        data_high[0] = fundus_img_high
        data_high[1] = oct_img_high.unsqueeze(0)

        # 处理标签
        label = label.argmax()

        # 返回两组数据和标签
        return (data_low, data_high), label



    def __len__(self):
        return len(self.file_list)

    def __resize_oct_data__(self, data):
        """
        Resize the data to the input size
        """
        data = data.squeeze()
        [depth, height, width] = data.shape
        scale = [self.input_D*1.0/depth, self.input_H *1.0/height, self.input_W*1.0/width]
        data = ndimage.interpolation.zoom(data, scale, order=0)
        # data = data.unsqueeze()
        return data

    
# class Multi_modal_data_OOD(Dataset):
#     """
#     load multi-view data
#     """
#
#     def __init__(self, root, ood_datapath,oodfile_list,ood_dataclass,modal_number,modalties,mode,condition,args, folder='folder0'):
#         """
#         :param root: data name and path
#         :param train: load training set or test set
#         """
#         super(Multi_modal_data_OOD, self).__init__()
#         self.root = root
#         self.mode = mode
#         self.data_path = self.root + folder + "/"
#         self.ood_data_path = ood_datapath
#         self.ood_dataclass = ood_dataclass
#         self.oodfile_list = oodfile_list
#         self.modalties = modalties
#         self.condition = condition
#         self.seed_idx = args.seed_idx
#
#         y_files = []
#
#         self.X = dict()
#         for m_num in range(modal_number):
#             x_files = []
#             c_m = modalties[m_num]
#             if c_m == self.ood_dataclass:
#                 for real_index in self.oodfile_list:
#                     file = self.ood_data_path + "/" + real_index + "/" + real_index + ".npy"
#                     x_files.append(file)
#                 self.X[m_num] = x_files
#             else:
#                 with open(join(self.data_path, self.mode + "_" + c_m + '.txt'),
#                           'r', encoding="gb18030", errors="ignore") as fx:
#                     files = fx.readlines()
#                     for file in files:
#                         file = file.replace('\n', '')
#                         x_files.append(file)
#                     self.X[m_num] = x_files
#         with open(join(self.data_path, self.mode + '_GT.txt'),
#                           'r') as fy:
#             yfiles = fy.readlines()
#             for yfile in yfiles:
#                 yfile = yfile.replace('\n', '')
#                 y_files.append(yfile)
#         self.y = y_files
#
#     def __getitem__(self, file_num):
#         data = dict()
#         np.random.seed(self.seed_idx)
#         for m_num in range(len(self.X)):
#             if self.modalties[m_num] == "FUN":
#                 # # Fundus read
#                 # fundus_img = np.load(self.dataset_root + "/" + real_index + "/" + real_index + ".npy").astype(
#                 #     np.float32)
#                 # fundus_img = fundus_img.transpose(1, 2, 0) / 255.0
#                 data[m_num] = np.load(self.X[m_num][file_num]).astype(np.float32)
#                 # plt.figure(4)
#                 # plt.imshow(data[m_num].transpose(1,2,0).astype(np.uint8))
#                 # plt.axis('off')
#                 # plt.show()
#                 data[m_num] = data[m_num]/255.0
#                 # resize to 256*256
#                 # np_km = np.load(self.X[m_num][file_num]).astype(np.float32)
#                 # Image_km = Image.fromarray(np.uint8(np_km.transpose(1, 2, 0)))
#                 # resize_km = Image_km.resize((256,256))
#                 # data[m_num] = np.array(resize_km).transpose(2, 1, 0).astype(np.float32)
#                 # plt.figure(5)
#                 # plt.imshow(data[m_num].transpose(1,2,0))
#                 # plt.axis('off')
#                 # plt.show()
#
#             else:
#                 kk = np.load(self.X[m_num][file_num]).astype(np.float32)
#                 # plt.figure(1)
#                 # plt.imshow(kk[0, :, :], cmap="gray")
#                 # plt.axis('off')
#                 # plt.show()
#                 # plt.figure(2)
#                 # plt.imshow(kk[127, :, :], cmap="gray")
#                 # plt.axis('off')
#                 # plt.show()
#                 kk = kk / 255.0
#                 # kk = np.load(self.X[m_num][file_num])
#                 # data[m_num] = np.expand_dims(kk, axis=0)
#                 # data[m_num] = self.__itensity_normalize_one_volume__(data[m_num])
#                 # data[m_num] = data[m_num] / 255.0
#                 # plt.figure(2)
#                 # PIL_noise = Image.fromarray(data[m_num][0, 60,:,:])
#                 # plt.imshow(PIL_noise)
#                 # plt.show()
#                 data[m_num] = np.expand_dims(kk.astype(np.float32), axis=0)
#
#         # plt.figure(1)
#         # plt.imshow(data[0].transpose(1,2,0))
#         # plt.show()
#         # plt.figure(2)
#         # plt.imshow(data[1][60,:,:].transpose(1,2,0))
#         # plt.show()
#         target_y = int(self.y[file_num])
#         target_y = np.array(target_y)
#         target =  torch.from_numpy(target_y)
#         return data, target
#
#     def __itensity_normalize_one_volume__(self, volume):
#         """
#         normalize the itensity of an nd volume based on the mean and std of nonzeor region
#         inputs:
#             volume: the input nd volume
#         outputs:
#             out: the normalized nd volume
#         """
#
#         pixels = volume[volume > 0]
#         mean = pixels.mean()
#         std = pixels.std()
#         out = (volume - mean) / std
#         out_random = np.random.normal(0, 1, size=volume.shape)
#         out[volume == 0] = out_random[volume == 0]
#         return out
#
#     def __len__(self):
#         return len(self.X[1])
# # def normalize(x, min=0):
# #     if min == 0:
# #         scaler = MinMaxScaler([0, 1])
# #     else:  # min=-1
# #         scaler = MinMaxScaler((-1, 1))
# #     norm_x = scaler.fit_transform(x)
# #     return norm_x
