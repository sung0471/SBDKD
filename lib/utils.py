import csv
import torch
import torch.nn as nn


class AverageMeter(object):
    """Computes and stores the average and current value"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


class Logger(object):
    def __init__(self, path, header):
        self.log_file = open(path, 'w')
        self.logger = csv.writer(self.log_file, delimiter='\t')

        self.logger.writerow(header)
        self.header = header

    def __del(self):
        self.log_file.close()

    def log(self, values):
        write_values = []
        for col in self.header:
            assert col in values
            write_values.append(values[col])

        self.logger.writerow(write_values)
        self.log_file.flush()


def load_value_file(file_path):
    with open(file_path, 'r') as input_file:
        value = float(input_file.read().rstrip('\n\r'))

    return value


def calculate_accuracy(outputs, targets):
    batch_size = targets.size(0)
    n_correct_avg = None

    conf_pred = outputs
    conf_target = targets.to(torch.long)

    out = dict()
    if n_correct_avg is None:
        _, pred = conf_pred.topk(1, 1, True)
        pred = pred.t()
        correct = pred.eq(conf_target.view(1, -1))
        n_correct_elems = correct.float().sum().clone().detach()

        out['conf'] = n_correct_elems / batch_size
    else:
        out['conf'] = n_correct_avg

    return out


def get_center_length(loc):
    # loc = number * [start, end]
    center = (loc[:, 1] + loc[:, 0]) / 2
    length = loc[:, 1] - loc[:, 0] + 1
    return torch.cat((center.view(-1, 1),       # center
                      length.view(-1, 1)), 1)   # length


def get_coordinate(loc):
    # loc = number * [center, length]
    start = loc[:, 0] - (loc[:, 1] - 1) / 2
    end = loc[:, 0] + (loc[:, 1] - 1) / 2
    return torch.cat((start.view(-1, 1),    # start
                      end.view(-1, 1)), 1)  # end


def encoding(loc, total_length, default_bar=None):
    variances = [0.1, 0.2]

    loc_data = get_center_length(loc)
    if default_bar is None:
        # loc = [batch_size, 2] : start, end
        # loc_data = [batch_size, 2] : center, length
        center = loc_data[:, 0] / (variances[0] * total_length)
        length = torch.log(loc_data[:, 1] / total_length) / variances[1]
    else:
        # loc = [default_bar_num, 2] : start, end
        # loc_data = [default_bar_num, 2] : center, length
        default = get_center_length(default_bar)

        center = (loc_data[:, 0] - default[:, 0]) / (variances[0] * default[:, 1])
        length = torch.log(loc_data[:, 1] / default[:, 1]) / variances[1]

    return torch.cat((center.view(-1, 1), length.view(-1, 1)), 1)


def decoding(loc, total_length, default_bar=None):
    variances = [0.1, 0.2]

    if default_bar is None:
        # loc = [batch_size, 2] : center, length
        center = loc[:, 0] * variances[0] * total_length
        length = torch.exp(loc[:, 1] * variances[1]) * total_length
    else:
        # loc = [default_bar_num, 2] : center, length
        default = get_center_length(default_bar)

        center = loc[:, 0] * variances[0] * default[:, 1] + default[:, 0]
        length = torch.exp(loc[:, 1] * variances[1]) * default[:, 1]

    center = center.view(-1, 1)
    length = length.view(-1, 1)

    new_loc = torch.cat((center, length), 1)

    return get_coordinate(new_loc)


def cal_iou(loc_a, loc_b, use_default=False):
    if not use_default:
        A = loc_a.size(0)
        B = loc_b.size(1)
        inter_start = torch.max(loc_a[:, 0], loc_b[:, 0])
        inter_end = torch.min(loc_a[:, 1], loc_b[:, 1])
        inter = inter_end - inter_start + 1
        inter = torch.clamp(inter, min=0)
        area_a = loc_a[:, 1] - loc_a[:, 0] + 1
        area_b = loc_b[:, 1] - loc_b[:, 0] + 1
    else:
        truths = loc_a.view(-1, 1, 2)
        default = loc_b.view(1, -1, 2)
        A = truths.size(0)
        B = default.size(1)

        inter_start = torch.max(truths[:, :, 0].unsqueeze(2).expand(A, B, 1),   # [A, B, 1]
                                default[:, :, 0].unsqueeze(2).expand(A, B, 1))
        inter_end = torch.min(truths[:, :, 1].unsqueeze(2).expand(A, B, 1),     # [A, B, 1]
                              default[:, :, 1].unsqueeze(2).expand(A, B, 1))
        inter = inter_end - inter_start + 1         # [A, B, 1]
        inter = torch.clamp(inter, min=0)
        inter = inter.squeeze(inter.dim() - 1)      # [A, B]
        area_a = (truths[:, :, 1] - truths[:, :, 0] + 1).expand_as(inter)       # [A,B]
        area_b = (default[:, :, 1] - default[:, :, 0] + 1).expand_as(inter)     # [A,B]

    union = area_a + area_b - inter

    return (inter / union).view(A, B)


def log_sum_exp(x):
    """Utility function for computing log_sum_exp while determining
    This will be used to determine unaveraged confidence loss across
    all examples in a batch.
    Args:
        x (tensor): conf_preds from conf layers
    """
    x_max = x.data.max()
    return torch.log(torch.sum(torch.exp(x - x_max), 1, keepdim=True)) + x_max


# Original author: Francisco Massa:
# https://github.com/fmassa/object-detection.torch
# Ported to PyTorch by Max deGroot (02/01/2017)
def nms(bars, scores, overlap=0.5, top_k=0):
    """Apply non-maximum suppression at test time to avoid detecting too many
    overlapping bounding boxes for a given object.
    Args:
        bars: (tensor) The location preds for the img, Shape: [num_priors,2].
        scores: (tensor) The class predscores for the img, Shape:[num_priors].
        overlap: (float) The overlap thresh for suppressing unnecessary boxes.
        top_k: (int) The Maximum number of box preds to consider.
    Return:
        The indices of the kept boxes with respect to num_priors.
    """

    # num : conf > 0.01??? default_bar??? ??????
    # bars = [num, 2] / scores = [num]
    # overlap = nms_threshold(0.45) / top_k = 5(default)
    keep = scores.new_zeros(scores.size(0)).to(torch.long)
    if bars.numel() == 0:   # number of elements
        return keep
    start = bars[:, 0]      # [num]
    end = bars[:, 1]        # [num]
    length = end - start + 1    # [num]
    v, idx = scores.sort(0)  # sort in ascending order
    # I = I[v >= 0.01]
    idx = idx[-top_k:]  # indices of the top-k largest vals

    # keep = torch.Tensor()
    count = 0
    while idx.numel() > 0:
        i = idx[-1]  # index of current largest val
        # keep.append(i)
        keep[count] = i
        count += 1
        if idx.size(0) == 1:
            break
        idx = idx[:-1]  # remove kept element from view
        # load bars of next highest vals
        ss = torch.index_select(start, 0, idx)   # [--num]
        ee = torch.index_select(end, 0, idx)     # [--num]
        # store element-wise max with next highest score
        ss = torch.clamp(ss, min=start[i].item())      # [--num]
        ee = torch.clamp(ee, max=end[i].item())        # [--num]
        l = ee - ss + 1     # [--num]
        # check length.. after each iteration
        inter = torch.clamp(l, min=0.0)         # [--num]
        # IoU = i / (area(a) + area(b) - i)
        rem_lengths = torch.index_select(length, 0, idx)  # [--num], load remaining lengths, not include top_1
        union = length[i] + rem_lengths - inter
        IoU = inter / union  # store result in iou

        check_policy = 1
        # keep elements with an IoU <= overlap
        check_iou = IoU.le(overlap)

        if check_policy == 1:
            # nms = 0.33
            idx = idx[check_iou]
        elif check_policy == 2:
            # nms = 0.67 and
            # keep elements with start[i] - ss != 1
            check_location = (ss - start[i].item()) != 1
            check_overlap = check_iou + check_location

            idx = idx[check_overlap == 2]
        else:
            # nms = 0.6 and
            # keep elements with not (start[i] - ss == 1 and IoU == 0.5)
            check_location = (ss - start[i].item()) == 1
            check_iou_2 = IoU == 0.5
            check_exception = check_location + check_iou_2 != 2

            check_overlap = check_iou + check_exception

            idx = idx[check_overlap == 2]

    return keep, count


def detection(out, sample_duration, num_classes, default_bar, conf_thresh, boundaries=None):
    loc, conf = out
    # frame_pos = torch.zeros(loc.size(0), loc.size(1), loc.size(2))
    # labels = torch.zeros(conf.size(0), conf.size(1), 1)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    default = default_bar.to(device)
    batch_size = loc.size(0)

    output = torch.zeros(batch_size, num_classes, default.size(0), 3).to(device)
    conf_pred = conf.transpose(2, 1)
    pred_num = torch.zeros(batch_size, num_classes, dtype=torch.int32)

    threshold = 0.6

    for batch_num in range(batch_size):
        total_length = sample_duration

        # assert loc.size(1) == self.default_bar.size(0)
        # frame_pos[i, :] = decoding(loc[i, :], total_length, default_bar=self.default_bar)
        # frame_pos[i, :] += start_boundaries[i]                  # [default_num, 2]
        # label = conf[i, :]
        # labels[i, :] = torch.argmax(label, dim=1).view(-1, 1)   # [default_num, 1]

        decoded_bars = decoding(loc[batch_num, :], total_length, default_bar=default)  # [default_num, 2]
        conf_scores = conf_pred[batch_num].clone().detach()  # [3, default_num]

        if boundaries is not None:
            bound_start = boundaries[batch_num]
            bound_end = boundaries[batch_num] + sample_duration - 1
            boundary = torch.cat((bound_start.view(-1), bound_end.view(-1)), 0).float()
        else:
            boundary = torch.Tensor([0, sample_duration - 1]).float().to(device)

        for cl in range(num_classes):
            c_mask = conf_scores[cl].gt(conf_thresh)  # [default_num]
            # for i in default_num,
            # if conf[i] > conf_thresh, num += 1
            scores = conf_scores[cl][c_mask]  # [num]
            if scores.size(0) == 0:
                continue
            l_mask = c_mask.unsqueeze(1).expand_as(decoded_bars)  # [default_num, 2]
            bars = decoded_bars[l_mask].view(-1, 2)  # [num, 2]
            v, idx = scores.sort(0, descending=True)  # sort in descending order

            count = 0
            if cl == 0:
                valid_idx = scores >= threshold
                count = valid_idx.int().sum().clone().detach().item()
                # count = idx.size(0)
                idx = idx[:count]
                output[batch_num, cl, :count] = torch.cat((bars[idx], scores[idx].unsqueeze(1)), 1)  # [top_k, 3]
            else:
                while count != idx.size(0) and scores[idx[count]].item() >= threshold:
                    output[batch_num, cl, count, :-1] = torch.round(bars[idx[count]] + boundary[0])
                    if boundary[0] <= output[batch_num, cl, count, 0] <= boundary[1] \
                            and boundary[0] <= output[batch_num, cl, count, 1] <= boundary[1]:
                        pass
                    else:
                        output[batch_num, cl, count, :-1] = torch.zeros(1, 2)
                    output[batch_num, cl, count, -1] = scores[idx[count]]
                    count += 1

            pred_num[batch_num, cl] = count

            # if cl == 0:
            #     total_num = idx.size(0) if idx.size(0) < top_k else top_k
            #     idx = idx[:total_num]
            #     output[batch_num, cl, :total_num] = \
            #         torch.cat((bars[idx],
            #                    scores[idx].unsqueeze(1)), 1)  # [top_k, 3]
            # else:
            #     # idx of highest scoring and non-overlapping boxes per class
            #     ids, count = nms(bars, scores, nms_thresh, top_k)
            #     output[batch_num, cl, :count] = \
            #         torch.cat((bars[ids[:count]],
            #                    scores[ids[:count]].unsqueeze(1)), 1)  # [count, 3]

    # [batch_size, all_result_bars_num, 3]
    # all_result_bars_num : ????????? ??? bar??? ??????(?????? top_k * num_classes)
    # 3 : start, end, conf
    # ?????? ????????? ???????????? ??????
    # flt = output.contiguous().view(batch_size, -1, 3)
    # _, idx = flt[:, :, -1].sort(1, descending=True)  # [batch_size, bars_num]
    # _, rank = idx.sort(1)  # [batch_size, bars_num], ??? idx ??? ??????
    # flt[(rank < top_k).unsqueeze(-1).expand_as(flt)].fill_(0)

    return output, pred_num


class Configure:
    def __init__(self, in_channel=2048, sample_duration=16, data_type='normal'):
        assert sample_duration in [8, 16, 32]
        self.sample_duration = sample_duration
        self.data_type = data_type

        channel_l = dict()
        # channel_l[8] = [(2048, 512, 1024), (1024, 256, 512)]
        # channel_l[16] = [(2048, 512, 1024), (1024, 256, 512), (512, 128, 256)]
        # channel_l[32] = [(2048, 512, 1024), (1024, 256, 512), (512, 128, 256), (256, 128, 256)]
        if sample_duration not in channel_l.keys():
            channel_l[sample_duration] = list()
        for i in range(int(sample_duration / 4)):
            if in_channel == 256:
                channel_l[sample_duration].append((in_channel, int(in_channel / 2), in_channel))
            else:
                channel_l[sample_duration].append((in_channel, int(in_channel / 4), int(in_channel / 2)))
            in_channel = int(in_channel / 2)
        self.channel_l = channel_l[sample_duration]

    def get_channel_list(self):
        return self.channel_l


if __name__ == '__main__':
    c_16 = Configure(16, policy='first')
    c_32 = Configure(32, policy='first')
    c_new = Configure(policy='second')
    default_bar_16 = c_16.get_default_bar()
    default_bar_32 = c_32.get_default_bar()
    default_bar_new = c_new.get_default_bar()
    print(default_bar_16)
    print(default_bar_32)
    print(default_bar_new)
    classification = {0.5: {2: [], 4: [], 8: [], 16: []},
                      0.33: {2: [], 4: [], 8: [], 16: []},
                      'back_gradual_cut':
                          {0.5: [0, 0, 0], 0.33: [0, 0, 0]}}
    GT_list = []
    for transition_len in range(2, 17):
        for start in range(16 - transition_len + 1):
            GT_list.append([float(start), float(start) + transition_len - 1])
    print(GT_list)
    for GT_start, GT_end in GT_list:
        GT_length = GT_end - GT_start + 1
        if GT_length == 2:
            transition_type = 2
        elif GT_length == 16:
            transition_type = 0
        else:
            transition_type = 1
        for start, end in default_bar_16:
            start = start.item()
            end = end.item()
            s = max(GT_start, start)
            e = min(GT_end, end)
            intersection = max(e - s + 1, 0)
            length = end - start + 1
            numerator = intersection
            denominator = GT_length + length - intersection
            if numerator/denominator >= 0.5:
                classification[0.5][length].append("[{}, {}] ({}/{})".format(GT_start, GT_end, numerator, denominator))
                classification['back_gradual_cut'][0.5][transition_type] += 1
                if transition_type == 0:
                    classification['back_gradual_cut'][0.5][1] += 1
            if numerator/denominator >= 0.33:
                classification[0.33][length].append("[{}, {}] ({}/{})".format(GT_start, GT_end, numerator, denominator))
                classification['back_gradual_cut'][0.33][transition_type] += 1
                if transition_type == 0:
                    classification['back_gradual_cut'][0.33][1] += 1
    import json
    json.dump(classification, open("match_GT_default_bar.json", 'wt'), indent=2)
