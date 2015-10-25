import os
import time
import datetime

import pandas

from glm_writer import write_glm
from xml_analyzer import analyze_xml


if __name__ == "__main__":
    topology_json = 'case/la/topology.json'
    config_json = 'case/la/config.json'
    data_csv = 'case/la/measurement.csv'
    steps = []
    for day in range(16, 17):
        for hr in range(10, 11):
            steps += [datetime.datetime(2015, 9, day, hour=hr, minute=m, second=0) for m in range(0, 60, 15)]
    file_dir = 'case/la/result/'

    # write glm files
    t1 = time.time()
    step2glm = dict()
    for step in steps:
        glm_file = write_glm(topology_json, config_json, step, data_csv, file_dir)
        if glm_file is None:
            print 'no such file - %s' % step
            continue
        step2glm[step] = glm_file
    print 'write glm avg time %f s' % (float(time.time()-t1)/len(steps))

    # calculate power flow by GridlabD
    t2 = time.time()
    step2xml = dict()
    for step, glm_file in step2glm.items():
        xml_file = glm_file.replace('.glm', '.xml')
        os.system('gridlabd %s --output %s' % (glm_file, xml_file))
        step2xml[step] = xml_file
    print 'cal pf avg time %f s' % (float(time.time()-t2)/len(step2glm))

    # analyze xml file
    t3 = time.time()
    df = pandas.DataFrame(columns=['timestamp', 'total_loss_real', 'total_power1_real',
                                   'percentage', 'total_trans_loss_real'])
    for step, xml_file in step2xml.items():
        result = analyze_xml(xml_file, step)
        if result is None:
            continue
        df = df.append([result])
    print 'analyze xml avg time %fs' % (float(time.time()-t3)/len(steps))

    # save line loss summary and delete other files
    with open(file_dir + 'line_loss_summary.csv', 'w+') as f:
        df.to_csv(f, sep=",")

    # todo delete the glm and xml files if necessary



