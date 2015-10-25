"""Write Glm file with specified topology.json, config.json and data.csv.

Modify the physical properties for lines, transformers if necessary.
"""

from collections import OrderedDict, namedtuple
import math
import datetime

import json
import pandas

# Physical Properties
# conductor: radius in ft, resistance in ohm/mile
Conductor = namedtuple('Conductor', 'name object_class radius resistance')
MV_CONDUCTOR = Conductor('Iris', 'overhead_line_conductor', 0.0122, 1.679)      # conductor for MV lines
LV_CONDUCTOR = Conductor('Shrimp', 'triplex_line_conductor', 0.01073, 0.825)    # conductor for LV lines
SD_CONDUCTOR = Conductor('AWG6', 'triplex_line_conductor', 0.00675, 2.224)      # conductor for Service Drops

# spacing between lines in ft
Spacing = namedtuple('Spacing', 'name object_class ab ac bc an bn cn')
MV_SPACING = Spacing('MV_spacing', 'line_spacing', 2.5, 4.5, 7, 4.272002, 5.656854, 5.0)

# diameter in inch, insulation_thickness in inch
LineDimension = namedtuple('LineDimension', 'name diameter thickness')
LV_LINE_DIM = LineDimension('triplex_lv', 0.522, 0.045)
SD_LINE_DIM = LineDimension('service_drop', 0.522, 0.045)

MV_LINE_CONFIG = 'MV_LINE_CONFIG'
LV_LINE_CONFIG = 'LV_LINE_CONFIG'
SERVICE_DROP_CONFIG = 'SERVICE_DROP_CONFIG'

# tag put before every node (glm does not support node name starting with numbers)
TAG_NODE = 'n'


def write_glm(topology_json, config_json, time_step, data_csv, file_dir):
    measure_snapshot = extract_measurement(data_csv, time_step)
    if measure_snapshot is None:
        return None
    print 'writing %s' % str(time_step)

    grid_config = json.load(open(config_json))
    grid_lines = json.load(open(topology_json))
    transformers = grid_lines['tr']
    del grid_lines['tr']
    grid_lines = sort_line_direction(grid_lines, grid_config['area2transformer'])

    glm_file = file_dir + time_step.strftime("%y%m%d-%H%M%S") + '.glm'
    fw = open(glm_file, 'w')
    fw.write(get_grid_summary(grid_lines, grid_config['area2phase'])[0])
    fw.write(get_network_flow(grid_lines, grid_config['area2transformer'])[0])

    glm = GlmFormat()
    fw.write('// header, clock, and module')
    fw.write(glm.header)
    fw.write(glm.clock)
    fw.write(glm.module)

    fw.write('// physical parameters and properties\n')
    fw.write(glm.get_line_conductor(MV_CONDUCTOR))
    fw.write(glm.get_line_spacing(MV_SPACING))
    fw.write(glm.get_line_config(MV_LINE_CONFIG, MV_CONDUCTOR, MV_SPACING))
    fw.write(glm.get_line_conductor(LV_CONDUCTOR))
    fw.write(glm.get_triplex_line_config(LV_LINE_CONFIG, LV_CONDUCTOR, LV_LINE_DIM))
    fw.write(glm.get_line_conductor(SD_CONDUCTOR))
    fw.write(glm.get_triplex_line_config(SERVICE_DROP_CONFIG, SD_CONDUCTOR, LV_LINE_DIM))

    fw.write('// transformers\n')
    for transformer in transformers:
        phase = grid_config['area2phase'][transformer['area_low']]
        trans_config = '%s_%s_%s' % (transformer['transformer'], phase, str(transformer['b']))
        fw.write(glm.get_trans_config(trans_config, phase))
        fw.write(glm.get_trans(phase, transformer, trans_config))

    fw.write('// lines\n')
    for sub, lines in grid_lines.items():
        phase = grid_config['area2phase'][sub]
        if 'mv' in sub:
            line_class = "overhead_line"
            config = MV_LINE_CONFIG
        else:
            line_class = 'triplex_line'
            config = LV_LINE_CONFIG
        for line in lines:
            if line['len'] <= 0:
                continue
            # whether service drop
            if 'sd' in line:
                config = SERVICE_DROP_CONFIG
            line2 = line.copy()
            fw.write(glm.get_line(line_class, phase, line2, config, sub))

    fw.write('// nodes\n')
    grid_nodes = dict()
    for sub, lines in grid_lines.items():
        nodes = set()
        for line in lines:
            nodes.add(line['a'])
            nodes.add(line['b'])
        grid_nodes[sub] = nodes
    for sub, nodes in grid_nodes.items():
        phase = grid_config['area2phase'][sub]
        measurement = {'voltage':120,'power_1':100+100j}
        for node in nodes:
            if node in grid_config['fixed_measurement']:
                measurement = grid_config['fixed_measurement'][node]
            elif node in grid_config['measure_id']:
                measure_id = grid_config['measure_id'][node]
                if measure_id in measure_snapshot:
                    measurement = measure_snapshot[measure_id]
                elif measure_id in grid_config['fixed_measurement']:
                    measurement = grid_config['fixed_measurement'][measure_id]
                else:
                    print 'unmeasured node', node, measure_id
            else:
                print 'unidentified node', node
            if 'mv' in sub:
                fw.write(glm.get_normal_node(phase, node, measurement))
            else:
                fw.write(glm.get_triplex_node(phase, node, measurement))

    fw.close()
    return glm_file


def extract_measurement(database, time_step):
    """Read measurement for the time_step from database"""
    # todo read directly from sql
    df = pandas.read_csv(database, sep=",")[['datetime', 'meter','rms_voltage','rms_current','true_power']]
    if type(time_step) is datetime.datetime:
        time_step = str(time_step)
    df_snapshot = df.loc[df['datetime'] == time_step]
    if df_snapshot.empty:
        return None
    measure_snapshot = dict()
    for index, row in df_snapshot.iterrows():
        meter = str(int(row['meter']))   # todo unify the meter names
        p = row['true_power']
        s = row['rms_voltage']*row['rms_current']
        if s**2 < p**2:
            q = 0
            print 'ignoring the q for ',
            print 's=', s, row['rms_voltage'], row['rms_current'],'p=', p
        else:
            q = math.sqrt(s**2 - p**2)
        v_level = 7200.0
        if 100 < float(row['rms_voltage']) < 150:
            v_level = 120.0
        measure_snapshot[meter] = {'nominal_voltage':v_level, 'power_1':complex(p,q)}
    return measure_snapshot


def sort_line_direction(grid_lines, area2transformer):
    """ Sort all lines such that a->b."""
    for sub, lines in grid_lines.items():
        if 'mv' in sub:
            # only sort tree-structured subdivisions
            continue
        sort_lines = []
        parents = [area2transformer[sub]]  # transformer is the root node
        while len(parents) > 0:
            head = parents.pop(0)
            for line in lines:
                if line['a'] == head:
                    sort_lines.append(line.copy())
                    parents.append(line['a'])
                    parents.append(line['b'])
                    lines.remove(line)
                elif line['b'] == head:
                    line_copy = line.copy()
                    line_copy['b'] = line['a']
                    line_copy['a'] = line['b']
                    sort_lines.append(line_copy)
                    parents.append(line['a'])
                    parents.append(line['b'])
                    lines.remove(line)
        assert len(lines) == 0
        grid_lines[sub] = sort_lines
    return grid_lines


def get_grid_summary(grid_lines, area2phase):
    summary = dict()
    for sub, lines in grid_lines.items():
        line_lens = 0
        line_count = 0
        service_lens = 0
        service_count = 0
        for line in lines:
            if 'len' not in line:    # virtual line e.g. transformer
                continue
            if 'sd' in line:        # service drop
                service_lens += line['len']
                service_count += 1
            else:
                line_count += 1
                line_lens += line['len']
        summary[sub] = {'n_line': line_count, 'len_line': line_lens, 'n_service': service_count, 'len_service': service_lens}
    summary_str = '//Simulation briefs : \n'
    for sub, record in summary.items():
        summary_str += ('//%s [%s] line [num %d, len %f ft] service drop [num %d, len %f ft] \n'
                        % (sub, area2phase[sub], record['n_line'], record['len_line'], record['n_service'],
                           record['len_service']))
    return summary_str, summary


def get_network_flow(grid_lines, area2transformer):
    # sort topology
    grid_flows = dict()
    for sub, sorted_lines in grid_lines.items():
        lines = sorted_lines[:]
        head2tail = dict()
        for line in lines:
            if 'sd' in line or 'len' not in line:
                # do not sort service drops nor virtual lines
                continue
            head = line['a']
            tail = line['b']
            if head in head2tail.keys():
                head2tail[head].append(tail)
            else:
                head2tail[head] = [tail]
        grid_flows[sub] = dict()
        potential_q = [area2transformer[sub]]
        back_source = dict()
        while len(potential_q) > 0:
            head = potential_q.pop(0)
            grid_flows[sub][head] = [head]
            cur_q = [head]
            while len(cur_q) > 0:
                cur = cur_q.pop(0)
                if cur not in head2tail:
                    continue
                tail = head2tail[cur].pop(0)
                grid_flows[sub][head].append(tail)
                cur_q.append(tail)
                while len(head2tail[cur]) > 0:
                    tail = head2tail[cur].pop(0)
                    potential_q.append(tail)
                    back_source[tail] = cur
        for tail, cur in back_source.items():
            grid_flows[sub][tail].insert(0, cur)
    flow_str = '// topology flow\n'
    for sub, flows in grid_flows.items():
        for head, flow in flows.items():
            flow_str += '// %s %s\n' % (sub, ', '.join(flow))
    flow_str += '\n'
    return flow_str, grid_flows


class GlmFormat():
    def __init__(self):
        self.header = '#set iteration_limit=2000\n' \
                      '#define stylesheet=C:\Users\gridlabd-3_0\n\n'

        self.clock = "clock {\n" \
                     "\ttimestamp '2000-01-01 0:00:00';\n" \
                     "\tstoptime '2000-01-01 0:00:20';\n" \
                     "\ttimezone EST+5EDT;\n}\n\n"

        self.module = 'module powerflow {\n' \
                      '\tsolver_method NR;\n' \
                      '};\n\n'

    def get_trans_config(self, name, phase):
        # todo consider other properties
        power_phase = 'power%s_rating' % phase[0]
        object_class = 'transformer_configuration'
        data = OrderedDict()
        data['name'] = name
        data['connect_type'] = 'SINGLE_PHASE_CENTER_TAPPED'
        data['install_type'] = 'POLETOP'
        data['primary_voltage'] = 7200.0
        data['secondary_voltage'] = 120.0
        data['power_rating'] = 100.0
        data[power_phase] = 100.0
        data['impedance'] = 0.006+0.0136j
        data['impedance1'] = 0.012+0.0204j
        data['impedance2'] = 0.012+0.0204j
        data['shunt_impedance'] = 259200+103680j
        return self._get_object_block(object_class, data)

    def get_trans(self, phase, trans, config):
        object_class = 'transformer'
        data = OrderedDict()
        data['phases'] = phase
        data['configuration'] = config
        # data['phases'] = phase
        data['from'] = trans['a']
        data['to'] = trans['b']
        if trans['a'][0].isdigit():
            data['from'] = TAG_NODE + trans['a'] # todo node's name no numbers
        if trans['b'][0].isdigit():
            data['to'] = TAG_NODE + trans['b']
        data['name'] = 't_%s_%s' % (data['from'], data['to'])
        data['nominal_voltage'] = 7200.0
        return self._get_object_block(object_class, data)

    def get_line_conductor(self, properties):
        data = OrderedDict()
        data['name'] = properties.name
        data['geometric_mean_radius'] = properties.radius
        data['resistance'] = properties.resistance
        return self._get_object_block(properties.object_class, data)

    def get_line_spacing(self, properties):
        object_class = 'line_spacing'
        data = OrderedDict()
        data['name'] = properties.name
        data['distance_AB'] = properties.ab
        data['distance_AC'] = properties.ac
        data['distance_BC'] = properties.bc
        data['distance_AN'] = properties.an
        data['distance_BN'] = properties.bn
        data['distance_CN'] = properties.cn
        return self._get_object_block(object_class, data)

    def get_line_config(self, name, conductor, spacing):
        object_class = 'line_configuration'
        data = OrderedDict()
        data['name'] = name
        data['conductor_A'] = conductor.name
        data['conductor_B'] = conductor.name
        data['conductor_C'] = conductor.name
        data['conductor_N'] = conductor.name
        data['spacing'] = spacing.name
        return self._get_object_block(object_class, data)

    def get_triplex_line_config(self, name, conductor, dimension):
        object_class = 'triplex_line_configuration'
        data = OrderedDict()
        data['name'] = name
        data['conductor_1'] = conductor.name
        data['conductor_2'] = conductor.name
        data['conductor_N'] = conductor.name
        data['insulation_thickness'] = dimension.thickness
        data['diameter'] = dimension.diameter
        return self._get_object_block(object_class, data)

    def get_line(self, line_class, phase, line, config, region):
        object_class = line_class
        data = OrderedDict()
        data['phases'] = phase
        data['from'] = line['a']    # todo node's name no numbers
        data['to'] = line['b']
        if line['a'][0].isdigit():
            data['from'] = TAG_NODE + line['a']  # todo node's name no numbers
        if data['to'][0].isdigit():
            data['to'] = ''.join([TAG_NODE, data['to']])
        data['name'] = '%s_%s_%s' % (region[0:2], data['from'], data['to'])
        data['configuration'] = config
        data['length'] = line['len']
        return self._get_object_block(object_class,data)

    def get_normal_node(self, phase, node, measurement):
        return self._get_node('node', phase, node, measurement)

    def get_triplex_node(self, phase, node, measurement):
        return self._get_node('triplex_node', phase, node, measurement)

    def _get_node(self, object_class, phase, node, measurement):
        data = OrderedDict()
        data['name'] = node
        if node[0].isdigit():
            data['name'] = TAG_NODE + node
        data['phases'] = phase
        for key,value in measurement.items():
            if key == 'bustype':
                data[key] = value
                continue
            data[key] = complex(value)
        return self._get_object_block(object_class, data)

    def _get_object_block(self, object_class, datadict):
        block = 'object %s {\n' % object_class
        for key, value in datadict.items():
            if isinstance(value, complex):
                if value.imag < -1e-4:
                    value = '%.3f%.3fj' % (value.real, value.imag)
                elif value.imag > 1e-4:
                    value = '%.3f+%.3fj' % (value.real, value.imag)
                else:
                    value = '%.3f' % value.real
            block += '\t%s %s;\n' % (key, value)
        block += '}\n\n'
        return block

