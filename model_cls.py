import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
from models import *
from thop import profile
import os
import copy


# 19.6.26. add parameter=model_type instead opt.model
# 19.7.16. moved from models/__init__.py
def generate_model(opt, model_type):
    assert model_type in ['resnet', 'alexnet', 'resnext']

    if model_type == 'alexnet':
        assert opt.alexnet_type in ['origin', 'dropout']
        model = deepSBD.deepSBD(model_type=opt.alexnet_type)
    else:
        assert opt.model_depth in [18, 34, 50, 101, 152]
        if model_type == 'resnet':
            from models.resnet import get_fine_tuning_parameters
            model = resnet.get_resnet(opt.model_depth, num_classes=opt.n_classes,
                                      sample_size=opt.sample_size, sample_duration=opt.sample_duration)
        else:
            model = resnext.get_resnext(opt.model_depth, num_classes=opt.n_classes,
                                       sample_size=opt.sample_size, sample_duration=opt.sample_duration)

    # 19.7.31. add deepcopy
    test_model = copy.deepcopy(model).to(opt.device)

    for_test_tensor = torch.randn(opt.batch_size, 3, opt.sample_duration, opt.sample_size, opt.sample_size).to(opt.device)
    if 'use_extra_layer' not in vars(opt).keys() or not opt.use_extra_layer:
        flops, params = profile(test_model, inputs=(for_test_tensor,))
    else:
        start_boundaries = torch.zeros(opt.batch_size).to(opt.device)
        for i in range(opt.batch_size):
            start_boundaries[i] = i * opt.sample_duration / 2
        flops, params = profile(test_model, inputs=(for_test_tensor, start_boundaries))
    print('Model : {}, (FLOPS: {}, Params: {})'.format(model_type, flops, params))

    return model


# 19.6.26. add parameter=model_type
# for knowledge distillation
def build_model(opt, model_type, phase):
    if phase != "test" and phase != "train":
        print("Error: Phase not recognized")
        return

    # num_classes = opt.n_classes
    # 19.6.26. add 'model_type' parameter
    model = generate_model(opt, model_type)

    # model=gradual_cls(opt.sample_duration,opt.sample_size,opt.sample_size,model,num_classes)
    # 19.5.15 if not opt.no_pretrained_model ??????
    # 19.5.23 opt.no_pretrained_model > opt.pretrained_model??? ??????
    # 19.8.5 train????????? ???????????? ????????? ??????????????? ??????
    if phase == 'train' and opt.pretrained_model:
        # 19.8.2 pretrained_path ???????????? ?????? ??????
        pretrained_model_type = model_type if model_type not in ['detector'] else opt.baseline_model
        pretrained_model_name = pretrained_model_type + '-' + str(opt.model_depth) + '-kinetics.pth'
        pretrained_path = os.path.join(opt.pretrained_dir, pretrained_model_name)
        if os.path.exists(pretrained_path):
            print("use pretrained model")
            model.load_weights(pretrained_path)
        else:
            raise Exception("there is no pretrained model : {}".format(pretrained_path))
    else:
        print("no pretrained model")

    # 19.4.17 model > cuda > parallel > train ??????
    # 19.5.15 model > benchmark > cuda > parallel > train ?????? (model_cls.py/build_model())
    # 19.5.16 model > train > parallel > benchmark > cuda ?????? (main_baseline.py/train_dataset)
    # 19.5.16 benchmark > model > cuda > parallel > train ?????? (model_cls.py/build_model())
    # 19.5.20 opt.model_type == 'old' ?????? ??????
    # if opt.no_cuda and opt.model_type == 'old':
    # model_type=='new', benchmark > model > train > parallel > cuda ?????? (main_baseline.py/build_final_model())
    # model_type=='old', benchmark > model > cuda > parallel > train ?????? (model_cls.py/build_model())
    # 19.5.23 opt.no_cuda > opt.cuda??? ??????
    # 19.5.30(?????????) benchmark > model > parallel > cuda > train ?????? (model_cls.py/build_model())
    # 19.6.4 remove opt.model_type == 'old' : 'new' is not trainable
    # 19.6.24 model > benchmark > parallel > cuda > train ?????? (model_cls.py/build_model())
    # 19.6.26. opt.model_type == 'new' ?????? ??????
    # benchmark??? ??????????????? ???????????? ????????? (model_type=new??? ???, main_baseline.py/build_final_model())
    # model_type=='new', model > train > benchmark > parallel > cuda (main_baseline.py/build_final_model())
    # model_type=='old', model > benchmark > parallel > cuda > train ?????? (model_cls.py/build_model())
    # 19.6.28. remove opt.model_type == 'old'
    # if opt.cuda and opt.model_type == 'old':
    if opt.cuda:
        # 19.5.15 benchmark ??????(model.to(device) ??????)
        # 19.5.16 main_baseline.py/train_dataset() > main()?????? ??????
        # 19.6.24 ?????? ?????? (model_cls.py/build_model())
        # 19.6.26 model generate ?????? ???????????? ?????? (model_type=old??? ???, main_baseline.py/main())
        # 19.7.1 main_baseline.py/main()?????? ??????
        # 19.7.10 benchmark=modelwise ???????????? ?????? ?????? (model_cls.py/build_model())
        torch.backends.benchmark = True

        # ?????? phase='train'??? phase='test'??? ????????? ??????
        # 19.5.14 use multi-gpu for training and testing
        # test??? device_ids=range(1) > device_ids=range(opt.gpu_num)??? ??????
        # 19.5.15 if phase == 'train' ?????? ??????(????????? ???????????? ?????? ??????)
        # 19.5.16 main_baseline.py/main()?????? ?????? / ?????? ??????
        # 19.5.20 if opt.no_cuda?????? ???????????? ?????? (model_type=old??? ??? ???????????????, ????????? ????????????)
        # 19.5.30(????????? ??????X) Parallel > model.to(device) ????????? ??????
        model = nn.DataParallel(model, device_ids=range(opt.gpu_num))
        # origin    model = model.cuda()
        # 19.3.8    model.to(device)
        # 19.4.17   model = model.cuda(device)
        # 19.5.15 ?????? ?????? ??? benchmark ??????
        #           model.to(device)
        # 19.5.16 main()?????? ?????? / ?????? ??????
        # 19.5.16   model = model.to(device)
        # 19.5.30(????????? ??????X) Parallel > model = model.to(device) ????????? ??????
        # 19.5.31   model.to(device)
        # 19.7.2    model = model.to(device)
        # 19.7.7 main_baseline.py/main?????? ??????
        # 19.7.10 model.inplace??? ?????? modelwise??? rollback
        # 19.10.18 device > opt.device
        model = model.to(opt.device)

    if phase == 'train':
        model.train()
    else:
        model.eval()

    return model
