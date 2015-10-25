import os
import math
import re
import cmath
from collections import OrderedDict

import xml.etree.ElementTree as ET


def analyze_xml(result_xml, time_step):
    if not os.path.exists(result_xml):
        return None
    tree = ET.parse(result_xml)
    root = tree.getroot()

    total_loss_real = 0
    for node in root.findall("./powerflow/triplex_line_list/triplex_line"):
        reading = None
        name = None
        for child in node:
            if child.tag == 'name':
                name = child.text
            if child.tag == 'power_losses':
                reading = child.text
        if name is None:
            continue
        # todo selective summation by checking name of node
        if reading is None:
            continue
        if reading == '+0+0j VA':
            continue
        if 'd VA' in reading:
            reading = reading[:-4]
        numbers = re.findall('[-+]?\ *[0-9]+\.?[0-9]*(?:[Ee]\ *-?\ *[0-9]+)?', reading)
        if ''.join(numbers) != reading:
            print numbers, reading
        assert ''.join(numbers) == reading
        loss = cmath.rect(float(numbers[0]), math.radians(float(numbers[1])))
        total_loss_real += loss.real

    total_power1_real = 0
    for node in root.findall("./powerflow/triplex_node_list/triplex_node"):
        reading = None
        name = None
        for child in node:
            if child.tag == 'name':
                name = child.text
            if child.tag == 'power_1':
                reading = child.text
        if name is None:
            continue
        # todo selective summation by checking name of node
        if reading is None:
            continue
        numbers = re.findall("[-+]?\d+[.]?\d*(?:[Ee]-\d+)?", reading)
        power1 = complex(float(numbers[0]), float(numbers[1]))
        assert ''.join(numbers) == reading[:-4]
        total_power1_real += power1.real

    total_trans_loss_real = 0
    for node in root.findall("./powerflow/transformer_list/transformer/power_losses"):
        reading = node.text
        if reading == '+0+0j VA':
            continue
        loss = 0
        if 'd VA' in reading:
            reading = reading[:-4]
            numbers = re.findall('[-+]?\ *[0-9]+\.?[0-9]*(?:[Ee]\ *-?\ *[0-9]+)?', reading)
            loss = cmath.rect(float(numbers[0]), math.radians(float(numbers[1])))
            loss = loss.real
        elif 'j VA' in reading or 'i VA' in reading:
            reading = reading[:-4]
            numbers = re.findall('[-+]?\ *[0-9]+\.?[0-9]*(?:[Ee]\ *-?\ *[0-9]+)?', reading)
            loss = float(numbers[0])
        if ''.join(numbers) != reading:
            print numbers, reading
        assert ''.join(numbers) == reading
        total_trans_loss_real += loss

    result_dict = OrderedDict()
    result_dict['timestamp'] = time_step
    result_dict['total_loss_real'] = total_loss_real
    result_dict['total_power1_real'] = total_power1_real
    result_dict['total_trans_loss_real'] = total_trans_loss_real
    result_dict['percentage'] = 0
    if total_power1_real > 0:
        result_dict['percentage'] = '%.3f%%' % float(total_loss_real/total_power1_real*100)
    return result_dict






