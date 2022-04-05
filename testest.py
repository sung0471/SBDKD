def solution(bridge_length, weight, truck_weights):
    # bridge_length : 다리 길이
    # weight : 다리 하중
    # truck_weights : 트럭들 무게 목록
    move = [0] * len(truck_weights)
    total_weight = 0
    start_pointer = 0
    end_pointer = 0
    answer = 0

    while not (len(truck_weights) == start_pointer + 1 == end_pointer and total_weight >= 0):
        if end_pointer < len(truck_weights):
            if total_weight + truck_weights[end_pointer] <= weight:
                total_weight += truck_weights[end_pointer]
                end_pointer += 1
        for i in range(start_pointer, end_pointer):
            move[i] += 1
            if move[i] > bridge_length:
                total_weight -= truck_weights[start_pointer]
                start_pointer = i + 1
        print(move)

        answer += 1
    a= str()
    a.upper()
    return answer

if __name__ == '__main__':
    bridge_length, weight, truck_weights = [2, 100, 100], [10, 100, 100], [[7, 4, 5, 6], [10],
                                                                           [10, 10, 10, 10, 10, 10, 10, 10, 10, 10]]
    for i in range(3):
        result = solution(bridge_length[i], weight[i], truck_weights[i])
        print(result)

    s = '3people unFollowed me ##fjaiofejiowef FFFFFFFFFFFFFFFFFFFF '
    str_split = s.split(' ')
    for i, _ in enumerate(str_split):
        if len(str_split[i]) != 0:
            str_split[i] = str_split[i].lower()
            str_split[i] = str_split[i].replace(str_split[i][0], str_split[i][0].upper(), 1)
        else:
            str_split.append(' ')
    answer = ' '.join(str_split)
    print(answer)

    msg = 'KAKAO'
    # init
    dictionary = dict()
    for i in range(ord('Z') - ord('A') + 1):
        dictionary[chr(ord('A') + i)] = i + 1
    dictionary['length'] = ord('Z') - ord('A') + 1

    answer = []
    start_idx = 0
    end_idx = 0
    count = 0
    while True:
        for length in range(start_idx + 1, len(msg) + 1):
            check_str = msg[start_idx:length]
            print(check_str)
            if check_str in dictionary.keys():
                output = dictionary[check_str]
                end_idx = length
            else:
                dictionary[check_str] = dictionary['length'] + 1
                dictionary['length'] += 1
                break
        answer.append(output)
        start_idx = end_idx
        if start_idx == len(msg):
            break

        count += 1
        if count > 100:
            break
    print(dictionary)
    print(answer)