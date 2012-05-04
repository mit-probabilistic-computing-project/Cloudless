import datetime,numpy as np,numpy.random as nr,scipy.special as ss,sys
import DPMB_State as ds
import DPMB as dm
import pylab,matplotlib,cPickle
##
import pdb

# takes in a dataset spec
# returns a dictionary describing the problem, containing:
# out["dataset_spec"] --- input dataset spec
# out["zs"] --- generating zs for training data
# out["xs"] --- list of raw vectors for the training data
# out["test_xs"] --- list of raw vectors for the test data
# out["test_lls_under_gen"] --- list of the log predictive probabilities of the test vectors under the generating model

def pickle_asyncmemoize(asyncmemo,file_str):
    with open(file_str,"wb") as fh:
        cPickle.dump(asyncmemo.memo,fh)

def unpickle_asyncmemoize(asyncmemo,file_str):
    from numpy import array
    with open(file_str,"rb") as fh:
        pickled_memo = cPickle.load(fh)

    ALL_RUN_SPECS = [eval(run_spec)[0] for run_spec in pickled_memo.keys()]
    new_memo = dict(zip([str((run_spec,)) for run_spec in ALL_RUN_SPECS],pickled_memo.values()))
    new_args = dict(zip([str((run_spec,)) for run_spec in ALL_RUN_SPECS],[(run_spec,) for run_spec in ALL_RUN_SPECS]))

    asyncmemo.memo = new_memo
    asyncmemo.args = new_args

    return ALL_RUN_SPECS

def gen_problem(dataset_spec):
    # generate a state, initialized according to the generation parameters from dataset spec,
    # containing all the training data only
    state = ds.DPMB_State(dataset_spec["gen_seed"],
                          dataset_spec["num_cols"],
                          dataset_spec["num_rows"],
                          init_alpha=dataset_spec["gen_alpha"],
                          init_betas=dataset_spec["gen_betas"],
                          init_z=dataset_spec["gen_z"],
                          init_x = None)
    problem = {}
    problem["dataset_spec"] = dataset_spec
    problem["zs"] = state.getZIndices()
    problem["xs"] = state.getXValues()
    test_xs, test_lls = state.generate_and_score_test_set(dataset_spec["N_test"])
    problem["test_xs"] = test_xs
    problem["test_lls_under_gen"] = test_lls
    return problem

global counts
counts = {}
def plot_helper(name, state):
    global counts
    if state not in counts:
        counts[state] = 0
    count = counts[state]
    state.plot(show=False,save_str = name + "-" + "%3d" % count + ".png")
    counts[state] += 1

def infer(run_spec):
    ##problem = run_spec["problem"]
    dataset_spec = run_spec["dataset_spec"] ## problem["dataset_spec"]
    verbose_state = "verbose_state" in run_spec and run_spec["verbose_state"]
    decanon_indices = run_spec.get("decanon_indices",None)

    if verbose_state:
        print "doing run: "
        for (k, v) in run_spec.items():
            if k.find("seed") != -1:
                print "   " + "hash(" + str(k) + ")" + " ---- " + str(hash(str(v)))
            else:
                print "   " + str(k) + " ---- " + str(v)
        
    print "initializing"

    # generate state exactly as gen_problem would have
    initial_state = ds.DPMB_State(dataset_spec["gen_seed"],
                                  dataset_spec["num_cols"],
                                  dataset_spec["num_rows"],
                                  init_alpha=dataset_spec["gen_alpha"],
                                  init_betas=dataset_spec["gen_betas"],
                                  init_z=dataset_spec["gen_z"],
                                  init_x = None)
    # all you need are the xs
    gen_xs = initial_state.getXValues()
    gen_zs = initial_state.getZIndices()
    inference_state = ds.DPMB_State(dataset_spec["gen_seed"],
                              dataset_spec["num_cols"],
                              dataset_spec["num_rows"],
                              # these could be the state at the end of an inference run
                              init_alpha=run_spec["infer_init_alpha"],
                              init_betas=run_spec["infer_init_betas"],
                              init_z=run_spec["infer_init_z"],
                              # 
                              init_x = gen_xs,decanon_indices=decanon_indices)

    print "...initialized"

    # FIXME : remove when done debugging resuming inference
    plot_helper("ground_truth", inference_state)

    transitioner = dm.DPMB(inf_seed = run_spec["infer_seed"],
                           state = inference_state,
                           infer_alpha = run_spec["infer_do_alpha_inference"],
                           infer_beta = run_spec["infer_do_betas_inference"])

    summaries = []

    summaries.append(
        transitioner.extract_state_summary(
            true_zs=gen_zs,verbose_state=verbose_state))

    print "saved initialization"

    time_seatbelt = None
    ari_seatbelt = None
    if "time_seatbelt" in run_spec:
        time_seatbelt = run_spec["time_seatbelt"]
    if "ari_seatbelt" in run_spec:
        ari_seatbelt = run_spec["ari_seatbelt"]

    last_valid_zs = None
    decanon_indices = None
    for i in range(run_spec["num_iters"]):
        transition_return = transitioner.transition(time_seatbelt=time_seatbelt,ari_seatbelt=ari_seatbelt,true_zs=gen_zs) # true_zs necessary for seatbelt 

        # FIXME : remove when done debugging resuming inference
        plot_helper("infer", inference_state)

        print "finished doing iteration" + str(i)
        summaries.append(
            transitioner.extract_state_summary(
            true_zs=gen_zs,verbose_state=verbose_state))
        print "finished saving iteration" + str(i)
        if transition_return is not None:
            summaries[-1]["break"] = transition_return
            break
        last_valid_zs = transitioner.state.getZIndices()
        decanon_indices = transitioner.state.get_decanonicalizing_indices()
    summaries[-1]["last_valid_zs"] = last_valid_zs
    summaries[-1]["decanon_indices"] = decanon_indices
    return summaries

def extract_measurement(which_measurement, one_runs_data):
    # measurement can be:
    # "predictive" FIXME
    if np.in1d(which_measurement,["num_clusters","ari","alpha","score"])[0]:
        return [summary[which_measurement] for summary in one_runs_data]
    elif which_measurement == "mean_beta":
        return [np.mean(summary["betas"]) for summary in one_runs_data]
    else:
        raise Exception("not implemented yet: " + str(which_measurement))

# FIXME: do generate_from_prior test (to make Ryan happy)

def plot_measurement(memoized_infer, which_measurement, target_problem, by_time = True
                     ,run_spec_filter=None,save_str=None,title_str=None,ylabel_str=None,legend_args=None
                     ,do_legend=True):
    matching_runs = []
    matching_summaries = []

    for (args, summaries) in memoized_infer.iter():
        run_spec = args[0]
        if run_spec_filter is not None and not run_spec_filter(run_spec):
            continue

        if str(run_spec["problem"]) == str(target_problem): ##FIXME: This is a hack, it should work without making str
            matching_runs.append(run_spec)
            matching_summaries.append(summaries)
            
    if len(matching_summaries) == 0:
        res = memoized_infer.report_status()
        if len(res["failures"]) > 0:
            print "**********************************************************"
            print "FIRST EXCEPTION: "
            print "**********************************************************"
            print res["failures"][0][1]
        raise Exception("No data to plot with these characteristics!")
    
    matching_measurements = []
    matching_linespecs = []
    matching_legendstrs = []
    for (run, summary) in zip(matching_runs, matching_summaries):
        try:
            matching_measurements.append(extract_measurement(which_measurement, summary))
        except Exception, e:
            print e
            
        linespec = {}
        legendstr = ""
        # for now, red if both hyper inference, black otherwise FIXME expand out all 4 bit options
        if run["infer_do_alpha_inference"] and run["infer_do_betas_inference"]:
            linespec["color"] = "red"
            legendstr += "inf_a=T,inf_b=T"
        elif run["infer_do_alpha_inference"] and not run["infer_do_betas_inference"]:
            linespec["color"] = "green"
            legendstr += "inf_a=T,inf_b=F"
        elif not run["infer_do_alpha_inference"] and run["infer_do_betas_inference"]:
            linespec["color"] = "magenta"
            legendstr += "inf_a=F,inf_b=T"
        else:
            linespec["color"] = "blue"
            legendstr += "inf_a=F,inf_b=F"

        # linestyle for initialization
        init_z = run["infer_init_z"]
        if init_z == 1:
            linespec["linestyle"] = "-"
            legendstr += ";init=P"
        elif init_z == "N":
            linespec["linestyle"] = "--"
            legendstr += ";init=N"
        elif init_z == None:
            linespec["linestyle"] = "-."
            legendstr += ";init=1"
        else:
            raise Exception("invalid init_z" + str(init_z))
        
            
        matching_linespecs.append(linespec)
        matching_legendstrs.append(legendstr)
    # FIXME: enable plots. still need to debug timing ***urgent***

    # unique_legendstrs = np.unique(matching_legendstrs)
    # unique_linespecs = []
    # for unique_legendstr in unique_legendstrs:
    #     unique_linespecs.append(matching_linespecs.index(

    pylab.figure()
    if do_legend:
        pylab.subplot(211)
    line_list = []
    if by_time:
        for measurement, summary, linespec in zip(matching_measurements, matching_summaries, matching_linespecs):
            xs = extract_time_elapsed_vs_iterations(summary)
            fh = pylab.plot(xs, measurement, color = linespec["color"], linestyle = linespec["linestyle"])
            pylab.xlabel("time (seconds)")
            line_list.append(fh[0])
    else:
        for measurement,linespec in zip(matching_measurements,matching_linespecs):
            fh = pylab.plot(measurement,color=linespec["color"], linestyle=linespec["linestyle"])
            pylab.xlabel("iter")
            line_list.append(fh[0])
        
    if title_str is not None:
        if type(title_str) is str:
            pylab.title(title_str)
        else:
            pylab.title(title_str[0])
    if ylabel_str is not None:
        pylab.ylabel(ylabel_str)

    if do_legend:
        pylab.subplot(212)
        if legend_args is None:
            legend_args = {"ncol":2,"prop":{"size":"medium"}}
        pylab.legend(line_list,matching_legendstrs,**legend_args)
    
    ##pylab.subplots_adjust(hspace=.4)
    if save_str is not None:
        pylab.savefig(save_str)

def try_plots(memoized_infer,which_measurements=None,run_spec_filter=None,do_legend=True):
    temp = [(k,v) for k,v in memoized_infer.iter()] ##FIXME : how better to ensure memo pullis it down?
    which_measurements = ["ari"] if which_measurements is None else which_measurements

    for problem_idx,target_problem in enumerate(extract_problems_from_memo(memoized_infer)):

        cluster_str = "clusters" + str(target_problem["dataset_spec"]["gen_z"][1]) ##
        col_str = "cols" + str(target_problem["dataset_spec"]["num_cols"])
        row_str = "rows" + str(target_problem["dataset_spec"]["num_rows"])
        config_str = "_".join([col_str,row_str,cluster_str])    

        for which_measurement in which_measurements:
            try:
                plot_measurement(memoized_infer, which_measurement, target_problem, run_spec_filter=run_spec_filter
                                    ,save_str="_".join([which_measurement,config_str,"time.png"]),title_str=[config_str,which_measurement],ylabel_str=which_measurement
                                    ,legend_args={"ncol":2,"markerscale":2},do_legend=do_legend)
                plot_measurement(memoized_infer, which_measurement, target_problem, run_spec_filter=run_spec_filter, by_time=False
                                    ,save_str="_".join([which_measurement,config_str,"iter.png"]),title_str=[config_str,which_measurement],ylabel_str=which_measurement
                                    ,legend_args={"ncol":2,"markerscale":2},do_legend=do_legend)
            except Exception, e:
                print e
    #plot_measurement(memoized_infer, "predictive", target_problem)

def extract_problems_from_memo(asyncmemo):
    from numpy import array
    ALL_RUN_SPECS = [eval(key)[0] for key in asyncmemo.memo.keys()]
    ALL_PROBLEM_STRS = dict(zip([str(run_spec["problem"]) for run_spec in ALL_RUN_SPECS],np.repeat(None,len(ALL_RUN_SPECS)))).keys()
    ALL_PROBLEMS = [eval(problem_str) for problem_str in ALL_PROBLEM_STRS]
    return ALL_PROBLEMS

def pickle_if_done(memoized_infer,file_str="pickled_jobs.pkl"):
    status = memoized_infer.report_status()
    if status["waiting"] != 0:
        print "Not done, not pickling"
        return False
    else:
        temp = [(k,v) for k,v in memoized_infer.iter()] ##FIXME : how better to ensure memo pullis it down?
        with open(file_str,"wb") as fh:
            cPickle.dump(memoized_infer.memo,fh)
        print "Done all jobs, memo pickled"
        return True

def calc_ari(group_idx_list_1,group_idx_list_2):
    # FIXME: be sure that the canonicalized vectors coming out of the above code go into ARI correctly
    ##https://en.wikipedia.org/wiki/Rand_index#The_contingency_table
    ##presumes group_idx's are numbered sequentially starting at 0
    Ns,As,Bs = gen_contingency_data(group_idx_list_1,group_idx_list_2)
    n_choose_2 = choose_2_sum(np.array([len(group_idx_list_1)]))
    cross_sums = choose_2_sum(Ns[Ns>1])
    a_sums = choose_2_sum(As)
    b_sums = choose_2_sum(Bs)
    return ((n_choose_2*cross_sums - a_sums*b_sums)
            /(.5*n_choose_2*(a_sums+b_sums) - a_sums*b_sums))

def extract_time_elapsed_vs_iterations(summary_seq):
    out = []
    cumsum = 0

    for summary in summary_seq:
        timing = summary["timing"]
        iter_sum = sum([timing[key] for key in ["alpha","betas","zs"]])
        cumsum += iter_sum
        out.append(cumsum)
    
    return out

def choose_2_sum(x):
    return sum(x*(x-1)/2.0)
            
def count_dict_overlap(dict1,dict2):
    overlap = 0
    for key in dict1:
        if key in dict2:
            overlap += 1
    return overlap

def gen_contingency_data(group_idx_list_1,group_idx_list_2):
    group_idx_dict_1 = {}
    for list_idx,group_idx in enumerate(group_idx_list_1):
        group_idx_dict_1.setdefault(group_idx,{})[list_idx] = None
    group_idx_dict_2 = {}
    for list_idx,group_idx in enumerate(group_idx_list_2):
        group_idx_dict_2.setdefault(group_idx,{})[list_idx] = None
    ##
    Ns = np.ndarray((len(group_idx_dict_1.keys()),len(group_idx_dict_2.keys())))
    for key1,value1 in group_idx_dict_1.iteritems():
        for key2,value2 in group_idx_dict_2.iteritems():
            Ns[key1,key2] = count_dict_overlap(value1,value2)
    As = Ns.sum(axis=1)
    Bs = Ns.sum(axis=0)
    return Ns,As,Bs

def renormalize_and_sample(logpstar_vec,verbose=False):
    p_vec = log_conditional_to_norm_prob(logpstar_vec)
    randv = nr.random()
    for (i, p) in enumerate(p_vec):
        if randv < p:
            if verbose:
                print " - hash of seed is " + str(hash(str(nr.get_state())))
                print " - draw,probs: ",i,np.array(np.log(p_vec)).round(2)
            return i
        else:
            randv = randv - p

def log_conditional_to_norm_prob(logp_list):
    maxv = max(logp_list)
    scaled = [logpstar - maxv for logpstar in logp_list]
    logZ = reduce(np.logaddexp, scaled)
    logp_vec = [s - logZ for s in scaled]
    return np.exp(logp_vec)

def cluster_vector_joint(vector,cluster,state):
    # FIXME: Is np.log(0.5) correct? (Probably, since it comes from symmetry plus beta_d < 1.0.) How does
    # this relate to the idea that we mix out of all-in-one by first finding the prior over zs (by first
    # washing out the effect of the data, by raising the betas so high that all clusters are nearly perfectly
    # likely to be noisy)
    alpha = state.alpha
    numVectors = len(state.get_all_vectors())
    if cluster is None or cluster.count() == 0:
        ##if the cluster would be empty without the vector, then its a special case
        alpha_term = np.log(alpha) - np.log(numVectors-1+alpha)
        data_term = state.num_cols*np.log(.5)
        retVal =  alpha_term + data_term
    else:
        boolIdx = np.array(vector.data,dtype=type(True))
        alpha_term = np.log(cluster.count()) - np.log(numVectors-1+alpha)
        numerator1 = boolIdx * np.log(cluster.column_sums + state.betas)
        numerator2 = (~boolIdx) * np.log(cluster.count() - cluster.column_sums + state.betas)
        denominator = np.log(cluster.count() + 2*state.betas)
        data_term = (numerator1 + numerator2 - denominator).sum()
        retVal = alpha_term + data_term
    if not np.isfinite(retVal):
        pdb.set_trace()
    if hasattr(state,"print_predictive") and state.print_predictive:
        mean_p = np.exp(numerator1 + numerator2 - denominator).mean().round(2) if "numerator1" in locals() else .5
        print retVal.round(2),alpha_term.round(2),data_term.round(2),state.vector_list.index(vector),state.cluster_list.index(cluster),mean_p
    if hasattr(state,"debug_predictive") and state.debug_predictive:
        pdb.set_trace()
        temp = 1 ## if this isn't here, debug start in return and can't see local variables?
    return retVal,alpha_term,data_term

def create_alpha_lnPdf(state):
    lnProdGammas = sum([ss.gammaln(cluster.count()) for cluster in state.cluster_list])
    lnPdf = lambda alpha: (ss.gammaln(alpha) + len(state.cluster_list)*np.log(alpha)
                           - ss.gammaln(alpha+len(state.vector_list)) + lnProdGammas)
    return lnPdf

def create_beta_lnPdf(state,col_idx):
    S_list = [cluster.column_sums[col_idx] for cluster in state.cluster_list]
    R_list = [len(cluster.vector_list) - cluster.column_sums[col_idx] for cluster in state.cluster_list]
    beta_d = state.betas[col_idx]
    lnPdf = lambda beta_d: sum([ss.gammaln(2*beta_d) - 2*ss.gammaln(beta_d)
                                + ss.gammaln(S+beta_d) + ss.gammaln(R+beta_d)
                                - ss.gammaln(S+R+2*beta_d) for S,R in zip(S_list,R_list)])
    return lnPdf

def calc_alpha_conditional(state):
    ##save original value, should be invariant
    original_alpha = state.alpha
    ##
    grid = state.get_alpha_grid()
    lnPdf = create_alpha_lnPdf(state)
    logp_list = []
    for test_alpha in grid:
        state.removeAlpha(lnPdf)
        state.setAlpha(lnPdf,test_alpha)
        logp_list.append(state.score)
    ##
    state.removeAlpha(lnPdf)
    state.setAlpha(lnPdf,original_alpha)
    ##
    return logp_list,lnPdf,grid

def calc_beta_conditional(state,col_idx):
    lnPdf = create_beta_lnPdf(state,col_idx)
    grid = state.get_beta_grid()
    logp_list = []
    ##
    original_beta = state.betas[col_idx]
    for test_beta in grid:
        state.removeBetaD(lnPdf,col_idx)
        state.setBetaD(lnPdf,col_idx,test_beta)
        logp_list.append(state.score)
    ##put everything back how you found it
    state.removeBetaD(lnPdf,col_idx)
    state.setBetaD(lnPdf,col_idx,original_beta)
    ##
    return logp_list,lnPdf,grid

def calculate_cluster_conditional(state,vector):
    ##vector should be unassigned
    ##new_cluster is auto appended to cluster list
    ##and pops off when vector is deassigned

    # FIXME: if there is already an empty cluster (either because deassigning didn't clear it out,
    #        or for some other reason), then we'll have a problem here. maybe a crash, maybe just
    #        incorrect probabilities.
    new_cluster = ds.Cluster(state)
    state.cluster_list.append(new_cluster)
    ##
    conditionals = []
    for cluster in state.cluster_list:
        cluster.assign_vector(vector)
        conditionals.append(state.score)
        cluster.deassign_vector(vector)
    ##
    return conditionals

def mle_alpha(clusters,points_per_cluster,max_alpha=100):
    mle = 1+np.argmax([ss.gammaln(alpha) + clusters*np.log(alpha) - ss.gammaln(clusters*points_per_cluster+alpha) for alpha in range(1,max_alpha)])
    return mle

def plot_data(data,fh=None,h_lines=None,title_str=None,interpolation="nearest",**kwargs):
    
    if fh is None:
        fh = pylab.figure()
    pylab.imshow(data,interpolation=interpolation,cmap=matplotlib.cm.binary,**kwargs)
    if h_lines is not None:
        xlim = fh.get_axes()[0].get_xlim()
        pylab.hlines(h_lines-.5,*xlim,color="red",linewidth=3)
    if title_str is not None:
        pylab.title(title_str)
    return fh

def bar_helper(x,y,fh=None,v_line=None,title_str=None,which_id=0):
    if fh is None:
        fh = pylab.figure()
    pylab.bar(x,y,width=min(np.diff(x)))
    if v_line is not None:
        pylab.vlines(v_line,*fh.get_axes()[which_id].get_ylim(),color="red",linewidth=3)
    if title_str is not None:
        pylab.ylabel(title_str)
    return fh


def mhSample(initVal,nSamples,lnPdf,sampler):
    samples = [initVal]
    priorSample = initVal
    for counter in range(nSamples):
        unif = nr.rand()
        proposal = sampler(priorSample)
        thresh = np.exp(lnPdf(proposal) - lnPdf(priorSample)) ## presume symmetric
        if np.isfinite(thresh) and unif < min(1,thresh):
            samples.append(proposal)
        else:
            samples.append(priorSample)
        priorSample = samples[-1]
    return samples

def printTS(printStr):
    print datetime.datetime.now().strftime("%H:%M:%S") + " :: " + printStr
    sys.stdout.flush()

def listCount(listIn):
    return dict([(currValue,sum(np.array(listIn)==currValue)) for currValue in np.unique(listIn)])

def set_seed(seed):
    if type(seed) == tuple:
        nr.set_state(seed)
    elif type(seed) == int:
        nr.seed(seed)
    else:
        raise Exception("Bad argument to set_seed: " + str(seed)) 

def get_seed():
    return nr.get_state()

