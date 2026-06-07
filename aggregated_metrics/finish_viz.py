from markov import *
from scarf_plot import *
import pickle as pkl

with open('/Users/kaia/desktop/patchwork_analysis/aggregated_metrics/markov_chain_structures.pkl', 'rb') as f:
    data = pkl.load(f)

    fixation_counts_correct = data['fixation_counts_correct']
    fixation_durations_correct = data['fixation_durations_correct']
    fixation_counts_incorrect = data['fixation_counts_incorrect']
    fixation_durations_incorrect = data['fixation_durations_incorrect']
    fixation_counts_patch = data['fixation_counts_patch']
    fixation_durations_patch = data['fixation_durations_patch']
    fixation_counts_no_patch = data['fixation_counts_no_patch']
    fixation_durations_no_patch = data['fixation_durations_no_patch']

    total_switches_correct = data['total_switches_correct']
    total_switches_incorrect = data['total_switches_incorrect']
    total_switches_patch = data['total_switches_patch']
    total_switches_no_patch = data['total_switches_no_patch']

    transition_df_correct = data['transition_df_correct']
    transition_df_incorrect = data['transition_df_incorrect']
    transition_df_patch = data['transition_df_patch']
    transition_df_no_patch = data['transition_df_no_patch']

    transition_dfs = {
      'transition_df_correct': transition_df_correct,
      'transition_df_incorrect': transition_df_incorrect,
      'transition_df_patch': transition_df_patch,
      'transition_df_no_patch': transition_df_no_patch,
    }
    print('Transition dataframe diagnostics:')
    for name, df in transition_dfs.items():
      print(f"{name}: shape={df.shape}, sum={df.to_numpy().sum()}")

    unique_aois_correct = data['unique_aois_correct']
    unique_aois_incorrect = data['unique_aois_incorrect']
    unique_aois_patch = data['unique_aois_patch']
    unique_aois_no_patch = data['unique_aois_no_patch']

    draw_markov_chain('correct', '',
                    fixation_counts_correct, fixation_durations_correct, 
                    transition_df_correct, unique_aois_correct, 
                    False)
    draw_markov_chain('incorrect', '',
                    fixation_counts_incorrect, fixation_durations_incorrect, 
                    transition_df_incorrect, unique_aois_incorrect, 
                    False)
    draw_markov_chain('patch', '',
                    fixation_counts_patch, fixation_durations_patch, 
                    transition_df_patch, unique_aois_patch, 
                    False)
    draw_markov_chain('no_patch', '',
                    fixation_counts_no_patch, fixation_durations_no_patch, 
                    transition_df_no_patch, unique_aois_no_patch, 
                  False)