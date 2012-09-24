#!python
import os
from collections import namedtuple
import hashlib
#
import matplotlib
matplotlib.use('Agg')
#
import Cloudless.examples.DPMB.settings as S
reload(S)
import Cloudless.examples.DPMB.MrJob.seed_inferer as si
reload(si)
import Cloudless.examples.DPMB.Tests.create_synthetic_data as csd
reload(csd)
import Cloudless.examples.DPMB.MrJob.consolidate_summaries as cs
reload(cs)


# data settings
make_own_dir = True

# problem settings
gen_seed = 0
num_rows = 8192
num_cols = 256
num_clusters = 4
beta_d = 1.
seed_filename = 'seed_list.txt'
image_save_str = os.path.join(S.data_dir, 'mrjob_problem_gen_state')
#
problem, problem_filename = csd.pkl_mrjob_problem(
    gen_seed, num_rows, num_cols, num_clusters, beta_d,
    image_save_str=image_save_str)
seed_full_filename = os.path.join(S.data_dir, seed_filename)
os.system('printf "0\n" > ' + seed_full_filename)

# inference settings
num_iters = 7
num_nodes_list = [1, 2, 4]
gibbs_init_filename = 'gibbs_init.pkl.gz'

# helper functions
create_args = lambda num_iters, num_nodes: [
    '--jobconf', 'mapred.map.tasks=' + str(num_nodes),
    # may need to specify mapred.map.tasks greater than num_nodes
    '--num-iters', str(num_iters),
    '--num-nodes', str(num_nodes),
    '--problem-file', problem_filename,
    seed_full_filename,
    ]

# gibbs init to be used by all subsequent inference
# iters=0, nodes=1
gibbs_init_args = ['--gibbs-init-file', gibbs_init_filename]
gibbs_init_args.extend(create_args(0, 1))
mr_job = si.MRSeedInferer(args=gibbs_init_args)
with mr_job.make_runner() as runner:
    runner.run()

# now run for each num_nodes
for num_nodes in num_nodes_list:
    print 'starting num_nodes = ' + str(num_nodes)
    infer_args = ['--resume-file', gibbs_init_filename]
    infer_args.extend(create_args(num_iters, num_nodes))
    mr_job = si.MRSeedInferer(args=infer_args)
    with mr_job.make_runner() as runner:
        runner.run()

summaries_dict, numnodes1_seed1 = cs.process_dirs([S.data_dir])

# create dir for results
if make_own_dir:
    get_hexdigest = lambda variable: \
        hashlib.sha224(str(variable)).hexdigest()[:10]
    settings_hash = {
        'gen_seed':gen_seed,
        'num_rows':num_rows,
        'num_cols':num_cols,
        'num_clusters':num_clusters,
        'beta_d':beta_d,
        'num_iters':num_iters,
        'num_nodes_list':num_nodes_list,
        }
    hex_digest = get_hexdigest(settings_hash)
    dest_dir = 'programmatic_mrjob_' + hex_digest
    dest_dir = os.path.join(S.data_dir, dest_dir)
    os.makedirs(dest_dir)
    #
    this_file = __file__
    data_files = os.path.join(S.data_dir, '*{png,txt,pkl.gz}')
    #
    system_str = ' '.join(['cp', this_file, dest_dir])
    os.system(system_str)
    system_str = ' '.join(['mv', data_files, dest_dir])
    system_str = ' '.join(['echo', system_str, '| bash'])
    os.system(system_str)
