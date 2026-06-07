from hmmlearn import hmm
import matplotlib.pyplot as plt
import graphviz

"""
Draw a Markov chain for a participant-task, where nodes are AOIs and edges represent switches between AOIs.
Nodes are labeled with, and sized according to, fixation duration and count.
"""
def draw_markov_chain(pid, task_no, 
                      fixation_counts, fixation_durations, 
                      transition_df, unique_aois,
                      individual=True,
                      min_edge_ratio=0.15):
    
    # draw participant-task-specific Markov chain
    markov_chain = graphviz.Digraph()

    # for every AOI, add a node to the graph with size proportional to fixation duration
    # label with percent total fixations and percent total fixation duration
    for AOI in unique_aois:
        fixation_count = fixation_counts[AOI]
        fixation_duration = fixation_durations[AOI]
        percent_total_fixations = fixation_count / sum(fixation_counts.values())
        percent_total_duration = fixation_duration / sum(fixation_durations.values())
        # .2 in the format string means to round to 2 decimal places, % formats as percentage
        markov_chain.node(AOI, label=f"{AOI}\n{percent_total_fixations:.2%} fixations\n{percent_total_duration:.2%} duration", 
                          width=str(percent_total_duration * 5), height=str(percent_total_duration * 5))
    
    # draw edges for each AOI this AOI switched to, labeled with transition probability
    for from_aoi in unique_aois:
        num_outgoing_transitions = transition_df.loc[from_aoi].sum()
        for to_aoi in unique_aois:
            if transition_df.loc[from_aoi, to_aoi] > 0 and from_aoi != to_aoi:
                ratio_of_switches = transition_df.loc[from_aoi, to_aoi] / num_outgoing_transitions
                # Only draw substantial transitions to reduce visual clutter.
                if ratio_of_switches >= min_edge_ratio:
                    markov_chain.edge(from_aoi, to_aoi, label=f"{ratio_of_switches:.2f}")
        
    if individual:
        markov_chain.render(f"{pid}_t{task_no}_markov_chain", format='png')
    else:
        markov_chain.render(f"{pid}_markov_chain", format='png')

"""
Plots the number of hidden states (k) against the AIC and BIC values for a given model, 
saving the plot as a PNG file.

Each model should share a lot of the hidden states, so we don't want k = 2 and k = 8 for another,
for example.
"""
def plot_k_vs_ic(ks, aics, bics, title=''):
    plt.figure(figsize=(10, 5))
    plt.plot(ks, aics, label='AIC', marker='o')
    plt.plot(ks, bics, label='BIC', marker='o')
    plt.xlabel('Number of Hidden States (k)')
    plt.ylabel('Information Criterion Value')
    plt.title(f'k vs. AIC and BIC for {title}')
    plt.legend()
    plt.xticks(ks)
    plt.grid()
    plt.savefig(f'k_vs_ic_{title}.png')

"""
Trains a Hidden Markov Model (HMM) on the given sequences and finds the optimal number of hidden states using BIC and AIC.

Parameters:
* sequences: array of sequences to train the HMM on
* lengths: list of lengths of each sequence
* n_features: number of features in the HMM
* title: title for the plot

Returns:
* best_bic_model: HMM model with the best BIC
* best_aic_model: HMM model with the best AIC
* best_bic_k: number of hidden states for the best BIC model
* best_aic_k: number of hidden states for the best AIC model
"""
def train_hmm(sequences, lengths, n_features, title=''):
    # Train the HMM, finding the optimal number of hidden states using BIC and AIC
    # try k from 2 through 15
    # There are ~9 AOIs
    best_bic_model = None
    best_aic_model = None
    best_bic = float('inf')
    best_aic = float('inf')
    best_bic_k = None
    best_aic_k = None
    bics = []
    aics = []
    ks = list(range(2, 16))
    for k in ks: 
        hmm_model = hmm.CategoricalHMM(n_components=k, n_features=n_features, n_iter=100)
        hmm_model.fit(sequences, lengths)
        bic = hmm_model.bic(sequences, lengths)
        aic = hmm_model.aic(sequences, lengths)
        bics.append(bic)
        aics.append(aic)
        if bic < best_bic:
            best_bic = bic
            best_bic_model = hmm_model
            best_bic_k = k
        if aic < best_aic:
            best_aic = aic
            best_aic_model = hmm_model
            best_aic_k = k
    
    # look at how fit changes with k visually
    plot_k_vs_ic(ks, aics, bics, title)

    return best_bic_model, best_aic_model, best_bic_k, best_aic_k