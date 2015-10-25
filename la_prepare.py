"""Prepare topology.json, config.json and data.csv for LA grid simulation.

Adjust the sql database host/database/user/password if necessary.
Adjust the meter replacement if necessary.
"""

from collections import OrderedDict
import sys
import datetime

import pandas
import json
import matplotlib.pyplot as plt
import psycopg2

# Sql connection
HOST = ''
DBNAME = ''
USER = ''
PASSWORD = ''

# meter replacement for broken meters
METER_OUT = [767, 222, 802, 759, 483, 747]
METER_IN = [455, 460, 549, 630, 648, 602]
METER_IN2OUT = dict()
for i in range(len(METER_OUT)):
    METER_IN2OUT[str(METER_IN[i])] = str(METER_OUT[i])

# tags for renaming
TAG_TRANSFORMER = 'TR'
TAG_MV_AREA = 'M'


def prepare_topology(la_json, topology_json):
    """ Process LA config file to match the specified format.

    Processes include:
    1) rename subdivision names, e.g. pink->mv (color->voltage level)
    2) rename the nodes shown in multiple areas (esp. when mv and lv share same poles, should be 2 nodes at each pole)
    3) remove redundant lines (some lines from the fig and .json file should be removed)
    4) add transformers (transformers should be add to some nodes)
    5) assign service drops to each lv subdivision and delete the red entry
    6) convert the lengths to feet
    """
    grid_lines = json.load(open(la_json, 'r'))
    grid_lines = remove_redundant_lines(grid_lines)
    grid_lines, transformers = add_transformers(grid_lines)
    grid_lines = deal_service_drops(grid_lines)
    grid_lines['tr'] = transformers
    grid_lines = rename_areas(grid_lines)
    grid_lines = rename_nodes(grid_lines)
    grid_lines = convert_length(grid_lines)

    with open(topology_json, 'w+') as f:
        json.dump(grid_lines, f, indent=2)


def remove_redundant_lines(grid_lines):
    """remove redundant lines (errors in the drawing.pdf and the json file). """
    remove_lines = [('12', '13'), ('14', '56'), ('86', '65'), ('29', '30'), ('84', '85'), ('24', '31')]
    combine_lines = ['61', '9', '62']
    for sub, lines in grid_lines.items():
        if 'red' in sub or 'pink' in sub:
            continue
        combine_lines_lens = []
        newlines = []
        for line in lines:
            if (line['a'], line['b']) in remove_lines or (line['b'], line['a']) in remove_lines:
                print 'remove', line, 'in', sub
                continue
            if (line['a'], line['b']) == (combine_lines[0], combine_lines[1]) \
                    or (line['a'], line['b']) == (combine_lines[1], combine_lines[0]):
                combine_lines_lens.append(line['len'])
                print 'remove', line, 'in', sub
                continue
            if {line['a'], line['b']} == {combine_lines[1], combine_lines[2]}:
                combine_lines_lens.append(line['len'])
                print 'remove', line, 'in', sub
                continue
            newlines.append(line)
        if len(combine_lines_lens) == 2:
            added_line = {'a': combine_lines[0], 'b': combine_lines[2], 'len': sum(combine_lines_lens)}
            print 'add', added_line
            newlines.append(added_line)
        grid_lines[sub] = newlines

    return grid_lines


def add_transformers(grid_lines, trans_nodes=None):
    """Add transformers between MV and LV."""
    if trans_nodes is None:
        trans_nodes = {'pink': "107", 'blue': "14", 'purple': "88", 'yellow': "44", 'green': "104", 'white': "77"}
    node2area = dict()
    for key, val in trans_nodes.items():
        node2area[val] = key
    transformers = []
    name_map = dict()
    for line in grid_lines['pink']:
        for end in ['a', 'b']:
            if line[end] in trans_nodes.values():
                if node2area[line[end]] is 'pink':
                    # not rename the MV area
                    continue
                if line[end] in [l1['b'] for l1 in transformers]:
                    # already counted
                    continue
                rename = ''.join((TAG_TRANSFORMER, line[end]))
                name_map[line[end]] = rename
                transformers.append(
                    {'a': rename, 'b': line[end], 'transformer': 'split', 'area_low': node2area[line[end]]})
                line[end] = rename
    # rename all other occurrences
    for line in grid_lines['pink']:
        for end in ['a', 'b']:
            if line[end] in name_map:
                line[end] = name_map[line[end]]
    return grid_lines, transformers


def deal_service_drops(grid_lines):
    # collect lv nodes
    sub2nodes = dict()
    for sub, lines in grid_lines.items():
        if 'red' in sub or 'pink' in sub:
            continue
        sub2nodes[sub] = set()
        for line in lines:
            sub2nodes[sub].add(line['a'])
            sub2nodes[sub].add(line['b'])
    # assign service drops to subdivisions
    for line in grid_lines['red']:
        regions = []
        for sub in sub2nodes.keys():
            if line['a'] in sub2nodes[sub]:
                line['b'] = line['house']
                line['sd'] = True
                del line['house']
                grid_lines[sub].append(line)
                regions.append(sub)
        if len(regions) > 1:
            print regions, line['a'], line['house']
    del grid_lines['red']
    return grid_lines


def rename_areas(grid_lines, area_map=None):
    if area_map is None:
        area_map = {'pink': "mv", 'blue': "lv1", 'purple': "lv2",
                    'yellow': "lv3", 'green': "lv4", 'white': "lv5"}
    sub2lines = OrderedDict()
    for color, sub in area_map.items():
        sub2lines[sub] = grid_lines[color]
    for trans in grid_lines['tr']:
        trans['area_low'] = area_map[trans['area_low']]
    sub2lines['tr'] = grid_lines['tr']
    return sub2lines


def rename_nodes(grid_lines):
    lv_nodes = set()
    for sub, lines in grid_lines.items():
        if 'mv' in sub or 'tr' in sub:
            continue
        for line in lines:
            lv_nodes.add(line['a'])
            lv_nodes.add(line['b'])
    # rename same node in mv area
    for line in grid_lines['mv']:
        for end in ['a', 'b']:
            if line[end] in lv_nodes:
                line[end] = ''.join([TAG_MV_AREA, line[end]])
    return grid_lines


def convert_length(grid_lines):
    for sub, lines in grid_lines.items():
        if 'tr' in sub:
            continue
        for line in lines:
            if 'len' in line:
                line['len'] *= 3.28084
    return grid_lines


def write_config(topology_json, config_json):
    try:
        conn = psycopg2.connect("host='%s' dbname='%s' user='%s' password='%s'" % HOST, DBNAME, USER, PASSWORD)
    except:
        print "I am unable to connect to the database"
        sys.exit(0)
    cur = conn.cursor()
    # creates dictionary which maps house ID to meter number
    cur.execute("SELECT id, street1, street2 FROM address ")
    rows = cur.fetchall()
    rowid_to_street = {}
    for row in rows:
        rowid_to_street[row[0]] = row[1]
    cur.execute("SELECT code, address_id FROM meter ")
    rows = cur.fetchall()
    house_to_meter = {}
    for row in rows:
        # account for totalizers
        if (rowid_to_street[row[1]] != ''):
            house_to_meter[rowid_to_street[row[1]]] = row[0]
    # prints the house-to-meter dictionary
    print ''
    print 'HOUSE-TO-METER MAPPING:'
    print house_to_meter

    measure_id_spec = dict()
    # lines and nodes to iterate and find measurement id
    grid_lines = json.load(open(topology_json, 'r'))
    for sub, lines in grid_lines.items():
        for line in lines:
            if sub == 'mv':
                measure_id_spec[line['a']] = 'MV_node'
                measure_id_spec[line['b']] = 'MV_node'
            else:
                measure_id_spec[line['a']] = 'triplex_connection'
                if 'sd' in line:
                    measure_id_spec[line['b']] = str(house_to_meter[line['b']])
                else:
                    measure_id_spec[line['b']] = 'triplex_connection'
    configs = dict()
    configs['area2phase'] = {"mv": "ABCN", "lv3": "AS", "lv1": "BS", "lv5": "BS", "lv4": "CS", "lv2": "CS"}
    configs['area2transformer'] = {"mv": "107", "lv3": "44", "lv1": "14", "lv4": "104", "lv5": "77", "lv2": "88"}
    configs['measure_id'] = measure_id_spec
    configs['fixed_measurement'] = {"107": {"bustype": "SWING", "voltage_A": "7200.7771", "voltage_B": "-3600.8886-6240.000j",
                                      "voltage_C": "-3600.8886+6240.000j", "nominal_voltage": 7203.7771},
                              "MV_node": {"voltage_A": "7200.7771", "voltage_B": "-3600.8886-6240.000j",
                                          "voltage_C": "-3600.8886+6240.000j", "nominal_voltage": 7201.7771},
                              "triplex_connection": {"power_1": "0", "nominal_voltage": 120}}

    # configs['meter_list'] = house_to_meter.values()
    json.dump(configs, open(config_json, 'w+'), indent=2)


def measurement_sql_to_csv(config_josn, simulation_steps, data_csv):
    """Draw measurement from sql to csv file."""
    try:
        conn = psycopg2.connect("host='sensor-07.andrew.cmu.edu' dbname='respawn' user='respawn' password='firefly'")
    except:
        print "I am unable to connect to the database"
        sys.exit(0)
    cur = conn.cursor()
    df = pandas.DataFrame()
    meter_trace = dict()

    meter_list = [str(meter) for meter in json.load(open(config_josn, 'r'))['measure_id'].values()
                  if meter not in json.load(open(config_josn, 'r'))['fixed_measurement']]
    for step in simulation_steps:
        record = dict()
        backward = 0
        while len(record.keys()) < len(meter_list):
            step2 = step - datetime.timedelta(seconds=backward)
            backward += 1
            cur.execute("Select voltage_avg, current_avg, true_power_avg, meter FROM reading "
                        "WHERE heartbeat_start='%s'" % step2)
            for row in cur.fetchall():
                meter = row[3]
                if meter in meter_list and meter not in record:
                    record[meter] = row
                if meter in METER_IN2OUT:
                    record[METER_IN2OUT[meter]] = row
            if backward % 120 == 0:
                print 'go back %d seconds searching for meters %s' % (backward, ",".join([str(meter) for meter in meter_list if meter not in record]))
            if backward > 300:
                print 'no data more than 300s, skip'
                break
        for meter in meter_list:
            if meter not in record:
                continue
            df = df.append([{'datetime': step, 'meter': meter, 'rms_voltage': record[meter][0],
                             'rms_current': record[meter][1], 'true_power': record[meter][2]}])
            if meter in meter_trace:
                meter_trace[meter].append(record[meter][2])
            else:
                meter_trace[meter] = [record[meter][2]]
    with open(data_csv, 'w+') as f:
        df.to_csv(f, sep=",")

    for meter in meter_list:
        if meter not in meter_trace:
            continue
        if sum(meter_trace[meter]) > 500:
            print 'Big load at meter', meter, 'sum', sum(meter_trace[meter])
        plt.plot(meter_trace[meter], label=meter)
    plt.grid()
    plt.show()


if __name__ == "__main__":
    prepare_topology('case/la/raw/la_grid_houses.json', 'case/la/topology.json')

    write_config('case/la/topology.json', 'case/la/config.json')

    steps = []
    for day in range(20, 21):
        for hr in range(10, 11):
            steps += [datetime.datetime(2015, 9, day, hour=hr, minute=m, second=0) for m in range(0, 60, 15)]
    measurement_sql_to_csv('case/la/config.json', steps, 'case/la/measurement.csv')
