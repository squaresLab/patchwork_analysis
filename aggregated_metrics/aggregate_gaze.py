from config import *
from markov import *
import pickle as pkl
import pandas as pd 
import numpy as np
from datetime import datetime
from scipy.stats import entropy
import os

ANALYSIS_CSV = '/home/kaia/patchwork_aggregation/timing_correctness_data.csv'

# Init data structures
analysis_df = pd.read_csv(ANALYSIS_CSV)

# don't forget to append file name for this
paths = get_subdirectories()
# paths = ['/Users/kaia/Desktop/patchwork_analysis/P17_t2_fixation_filtered.csv', # overfitting, not correct
#          '/Users/kaia/Desktop/patchwork_analysis/P24_t2_fixation_filtered.csv'] # P24, t2: control, correct
    
# we want individual markov chains
# but we want to build aggregate markov chains for correct vs. incorrect sessions, and for patch and no patch sessions

relevant_aois = ['Source Code', 'Test and Runtime Feedback', 'Browser', 'Patch', 'Tests']
scarf_segments = []

fixation_counts_correct = {}
fixation_durations_correct = {}
fixation_counts_incorrect = {}
fixation_durations_incorrect = {}
fixation_counts_no_patch = {}
fixation_durations_no_patch = {}
fixation_counts_patch = {}
fixation_durations_patch = {}

# you will also need decoded sequences
decoded_fixation_sequences_correct = []
decoded_fixation_sequences_incorrect = []
decoded_fixation_sequences_no_patch = []
decoded_fixation_sequences_patch = []

"""
Aggregate fixation counts, durations, and sequences across participant-tasks.
"""
def aggregate(full_counts, counts, 
              full_durations, durations, 
              decoded_full_sequences, decoded_sequence):
    for AOI in counts:
        if AOI not in full_counts:
            full_counts[AOI] = 0
        full_counts[AOI] += counts[AOI]
    for AOI in durations:
        if AOI not in full_durations:
            full_durations[AOI] = 0
        full_durations[AOI] += durations[AOI]
    
    decoded_full_sequences.append(decoded_sequence)

    return full_counts, full_durations, decoded_full_sequences

"""
Get sequence of AOIs and the total number of switches between AOIs for a participant-task.
"""
def get_aoi_sequence_and_switches(aoi_sequences):
    if len(aoi_sequences) == 0:
        return pd.DataFrame(), [], 0

    # this is an individual's sequence
    if isinstance(aoi_sequences[0], str):
        aoi_sequences = [aoi_sequences]
    else:
        # Normalize to a list of AOI sequences.
        normalized_sequences = []
        for seq in aoi_sequences:
            if isinstance(seq, np.ndarray):
                normalized_sequences.append(seq.flatten().tolist())
            else:
                normalized_sequences.append(list(seq))
        aoi_sequences = normalized_sequences

    # get unique AOIs across all sequences
    unique_aois = set()
    for aoi_sequence in aoi_sequences:
        unique_aois.update(aoi_sequence)
    
    # sort them for consistent ordering
    unique_aois = sorted(unique_aois)
    transition_df = pd.DataFrame(0, index=unique_aois, columns=unique_aois)

    total_switches = 0
    for aoi_sequence in aoi_sequences:
        for i in range(len(aoi_sequence) - 1):
            from_aoi = aoi_sequence[i]
            to_aoi = aoi_sequence[i + 1]
            if from_aoi != to_aoi:
                total_switches += 1
                transition_df.loc[from_aoi, to_aoi] += 1.0
    
    return transition_df, unique_aois, total_switches

"""
These are metrics that are not relevant to the ART ANOVA analysis. 
These represent hypotheses that our participants have raised that we will test with mixed effects regression models (RQs 2 and 3).
    
Calculate (and put into analysis_df):
* number of non-test files that were fixated on
* shannon entropy of fixation durations across non-test files
* time to first fixation on buggy method
* average fixation duration across whole session
* time to first fixation on patch (if applicable)
* average fixation duration on patch (if applicable)
* attention switching frequency (aoi switches / time, modulo '-' or 'OOB')

Parameters:
* df: participant-task-specific dataframe with all gaze data
* analysis_df: dataframe with one row per participant-task, where we will insert aggregated metrics
* mask: boolean mask to identify the row in analysis_df corresponding to this participant-task
* has_patch: boolean indicating whether this participant-task had a patch or not
* total_switches: total number of attention switches for this participant-task

Returns:
* analysis_df: dataframe with one row per participant-task, where we have inserted the calculated metrics
"""
def calculate_non_art_metrics(df, analysis_df, mask, has_patch, total_switches):
    file_fixation_durations = []

    # to test our hypothesis about narrowness of search vs. having a patch
    unique_paths = df['file_AOI'].dropna().unique()
    analysis_df.loc[mask, 'num_files_looked_at'] = len(unique_paths)
    # get shannon entropy of fixation durations across unique paths
    # we will need to find majority file 
    for path in unique_paths:
        # find fixation ids of all fixations with file AOI of this path
        fixation_ids_for_path = df[df['file_AOI'] == path]['fixation_group_id'].unique()
        # sum the durations of these fixation ids and add to list
        total_duration_for_path = (
            df[df['fixation_group_id'].isin(fixation_ids_for_path)]
            .groupby('fixation_group_id')['fixation_group_duration']
            .first()
            .sum()
        )
        file_fixation_durations.append(total_duration_for_path)

    analysis_df.loc[mask, 'fixation_duration_entropy'] = entropy(file_fixation_durations)

    ttff_buggy_method = None
    # find rows where on_method is true and is a fixation
    # sort by timestamp, get the first one, find timestamp delta from start of session
    df.sort_values('timestamp', inplace=True)
    on_method_fixations = df[(df['on_method'] == True) & (~pd.isna(df['fixation_group_id']))]
    # they could never look at it, so check if this is empty (otherwise nan)
    first_on_method_fixation = on_method_fixations.iloc[0] if not on_method_fixations.empty else None
    if first_on_method_fixation is not None:
        ttff_buggy_method = ((first_on_method_fixation['timestamp'] - df['timestamp'].min()) / 1000) / 60  # convert to minutes
    else:
        ttff_buggy_method = np.nan
    analysis_df.loc[mask, 'ttff_buggy_method'] = ttff_buggy_method

    # get all fixation durations and average them 
    fixation_durations = df.groupby('fixation_group_id')['fixation_group_duration'].first()
    avg_fixation_duration = fixation_durations.mean()
    analysis_df.loc[mask, 'avg_fixation_duration'] = avg_fixation_duration

    task_time = (df['timestamp'].max() - df['timestamp'].min()) / 1000 / 60  # convert to minutes

    ttff_patch = None
    avg_fixation_duration_patch = None
    if has_patch:
        patch_fixations = df[(df['AOI'] == 'Patch') & (~pd.isna(df['fixation_group_id']))]
        first_patch_fixation = patch_fixations.iloc[0] if not patch_fixations.empty else None
        if first_patch_fixation is not None:
            ttff_patch = ((first_patch_fixation['timestamp'] - df['timestamp'].min()) / 1000) / 60  # convert to minutes
        else:
            ttff_patch = np.nan
        analysis_df.loc[mask, 'ttff_patch'] = ttff_patch

        if not patch_fixations.empty:
            patch_fixation_durations = patch_fixations.groupby('fixation_group_id')['fixation_group_duration'].first()
            avg_fixation_duration_patch = patch_fixation_durations.mean()
        else:
            avg_fixation_duration_patch = np.nan
        analysis_df.loc[mask, 'avg_fixation_duration_patch'] = avg_fixation_duration_patch
    
    print(f"Total switches for {analysis_df.loc[mask, 'PID'].values[0]} task {analysis_df.loc[mask, 'task_no'].values[0]}: {total_switches}")
    # attention switching to look at the rate of triangulation between informational resources 
    analysis_df.loc[mask, 'attention_switching_rate'] = total_switches / task_time
    
    return analysis_df

# for each usable (non-outlier) fixation-filtered CSV:
for path in paths:
    print(f"Processing {path} at {datetime.now()}...", flush=True)

    # construct path
    pid = os.path.basename(os.path.dirname(path))
    task = os.path.basename(path)
    task_no = task.lstrip("t")
    task_no = np.int64(task_no)
    filename = f"{pid}_{task}_fixation_filtered.csv"
    path = os.path.join(path, filename)
    df = pd.read_csv(path)

    df.sort_values('timestamp', inplace=True)
    GLITCH_GAP_MS = 30 * 60 * 1000  # 30 min; real within-task gaps are far smaller
    gaps = df['timestamp'].diff()
    for idx, gap in gaps[gaps > GLITCH_GAP_MS].items():
        df.loc[idx:, 'timestamp'] -= gap   # shift this jump and everything after

    # Rename all cells in the AOI column that are 'Execution Inspection' to 'Test and Run Output'
    # and rename Test and Run Output to Test and Runtime Feedback (to reflect recent AOI decision)
    df['AOI'] = df['AOI'].replace('Execution Inspection', 'Test and Run Output')
    df['AOI'] = df['AOI'].replace('Test and Run Output', 'Test and Runtime Feedback')

    # fixation_group_id is the colname that has fixation IDs
    fixation_ids = np.array(sorted(df['fixation_group_id'].dropna().unique()), dtype=int)
    # now look for the rows in df that have each fixation ID, and find the majority AOI
    df['fixation_AOI'] = np.nan
    df['fixation_AOI'] = df['fixation_AOI'].astype(object)

    df['file_AOI'] = np.nan
    df['file_AOI'] = df['file_AOI'].astype(object)
    
    for fixation_id in fixation_ids:
        fixation_rows = df[df['fixation_group_id'] == fixation_id]
        majority_AOI = fixation_rows['AOI'].mode()[0]  # get the most common AOI for this fixation
        df.loc[df['fixation_group_id'] == fixation_id, 'fixation_AOI'] = majority_AOI
        
        if majority_AOI == 'Source Code':
            # if they're looking at the editor, find the majority file they're looking at
            majority_file = fixation_rows['path'].mode()[0]
            df.loc[df['fixation_group_id'] == fixation_id, 'file_AOI'] = majority_file

    # use analysis df to find whether this is a task with a patch, and whether they got it correct or not
    got_correct = analysis_df[(analysis_df['PID'] == pid) & (analysis_df['task_no'] == task_no)]['correct'].values[0]
    if got_correct == 'Y':
        got_correct = True
    else:
        got_correct = False

    # record this for the scarf plots
    condition_label = analysis_df[(analysis_df['PID'] == pid) & (analysis_df['task_no'] == task_no)]['condition'].values[0]

    has_patch = analysis_df[(analysis_df['PID'] == pid) & (analysis_df['task_no'] == task_no)]['condition'].values[0]
    if has_patch == 'overfitting' or has_patch == 'correct':
        has_patch = True
    else:
        has_patch = False

    # dictionaries to record number of fixations for each AOI and total fixation duration for each AOI
    fixation_counts = {}
    fixation_durations = {}

    # count fixations and fixation durations for each AOI
    for AOI in df['fixation_AOI'].dropna().unique():
        AOI_rows = df[df['fixation_AOI'] == AOI]
        # find unique fixation IDs in these rows that are fixations on this AOI
        fixation_ids_in_AOI = AOI_rows['fixation_group_id'].unique()
        fixation_counts[AOI] = len(fixation_ids_in_AOI)

        # durations should be a sum of fixation durations of individual fixations on this AOI
        # so look at the first value from each unique fixation ID
        fixation_durations[AOI] = AOI_rows.groupby('fixation_group_id')['fixation_group_duration'].first().sum()
    
    # Build an AOI sequence per participant-task, omitting '-' and OOB transitions
    # Used in Markov chain construction and attention switching metric.
    decoded_aoi_sequence = []
    session_start = df['timestamp'].min()
    for fixation_id in fixation_ids:
        fixation_rows = df[df['fixation_group_id'] == fixation_id]
        if fixation_rows.empty:
            continue
        aoi = fixation_rows['fixation_AOI'].iloc[0]

        # scarf row (keep all AOIs, bucket non-core as Other or Missing for gazes with only one eye valid)
        # FIXME: check to make sure this makes sense
        fixation_start_ts = fixation_rows['timestamp'].min()
        fixation_duration_ms = fixation_rows['fixation_group_duration'].iloc[0]
        start_min = (fixation_start_ts - session_start) / 1000 / 60
        duration_min = fixation_duration_ms / 1000 / 60
        end_min = start_min + duration_min

        if aoi == "-":
            scarf_aoi = 'Missing'
        elif aoi in relevant_aois:
            scarf_aoi = aoi
        else:
            scarf_aoi = 'Other'

        scarf_segments.append({
            'PID': pid,
            'task_no': task_no,
            'condition': condition_label,
            'fixation_group_id': fixation_id,
            'start_min': start_min,
            'duration_min': duration_min,
            'end_min': end_min,
            'scarf_aoi': scarf_aoi
        })

        # simply don't include AOIs that we don't care about
        if aoi not in relevant_aois:
            continue
        decoded_aoi_sequence.append(aoi)

    transition_df, unique_aois, total_switches = get_aoi_sequence_and_switches(decoded_aoi_sequence)

    # pickle all data required for this participant-task so we can draw a chain later
    with open(f'{pid}_t{task_no}_markov_chain_data.pkl', 'wb') as f:
        pkl.dump({
            'pid': pid,
            'task_no': task_no,
            'fixation_counts': fixation_counts,
            'fixation_durations': fixation_durations,
            'transition_df': transition_df,
            'unique_aois': unique_aois
        }, f)

    # now aggregate the counts, durations, and sequences 
    if got_correct:
        (fixation_counts_correct, fixation_durations_correct, 
        decoded_fixation_sequences_correct) = \
        aggregate(fixation_counts_correct, fixation_counts, fixation_durations_correct, 
                      fixation_durations, decoded_fixation_sequences_correct, decoded_aoi_sequence)
    else:
        (fixation_counts_incorrect, fixation_durations_incorrect,
        decoded_fixation_sequences_incorrect) = \
        aggregate(fixation_counts_incorrect, fixation_counts, fixation_durations_incorrect, 
                      fixation_durations, decoded_fixation_sequences_incorrect, decoded_aoi_sequence)
    
    if has_patch:
        (fixation_counts_patch, fixation_durations_patch,
        decoded_fixation_sequences_patch) = \
        aggregate(fixation_counts_patch, fixation_counts, fixation_durations_patch, 
                      fixation_durations, decoded_fixation_sequences_patch, decoded_aoi_sequence)
    else:
        (fixation_counts_no_patch, fixation_durations_no_patch,
        decoded_fixation_sequences_no_patch) = \
        aggregate(fixation_counts_no_patch, fixation_counts, fixation_durations_no_patch, 
                      fixation_durations, decoded_fixation_sequences_no_patch, decoded_aoi_sequence)

    # insert fixation counts and fixation durations into all columns, finishing ART prep
    mask = (analysis_df['PID'] == pid) & (analysis_df['task_no'] == task_no)
    for AOI in fixation_counts:
        analysis_df.loc[mask, f'{AOI}_fixation_count'] = fixation_counts[AOI]
    for AOI in fixation_durations:
        analysis_df.loc[mask, f'{AOI}_fixation_duration'] = fixation_durations[AOI]
    
    # calculate metrics for testing interview-derived hypotheses for RQs 2 and 3 and insert into analysis_df
    analysis_df = calculate_non_art_metrics(df, analysis_df, mask, has_patch, total_switches)

# write analysis df with fixation counts and durations to csv
analysis_df.to_csv('timing_correctness_data_with_gaze.csv', index=False)

# get data structures for correct and incorrect and patch and no patch
transition_df_correct, unique_aois_correct, total_switches_correct = get_aoi_sequence_and_switches(decoded_fixation_sequences_correct)
transition_df_incorrect, unique_aois_incorrect, total_switches_incorrect = get_aoi_sequence_and_switches(decoded_fixation_sequences_incorrect)
transition_df_patch, unique_aois_patch, total_switches_patch = get_aoi_sequence_and_switches(decoded_fixation_sequences_patch)
transition_df_no_patch, unique_aois_no_patch, total_switches_no_patch = get_aoi_sequence_and_switches(decoded_fixation_sequences_no_patch)

with open('markov_chain_structures.pkl', 'wb') as f:
    pkl.dump({
        'transition_df_correct': transition_df_correct,
        'transition_df_incorrect': transition_df_incorrect,
        'transition_df_patch': transition_df_patch,
        'transition_df_no_patch': transition_df_no_patch,
        'unique_aois_correct': unique_aois_correct,
        'unique_aois_incorrect': unique_aois_incorrect,
        'unique_aois_patch': unique_aois_patch,
        'unique_aois_no_patch': unique_aois_no_patch,
        'total_switches_correct': total_switches_correct,
        'total_switches_incorrect': total_switches_incorrect,
        'total_switches_patch': total_switches_patch,
        'total_switches_no_patch': total_switches_no_patch,
        'fixation_counts_correct': fixation_counts_correct,
        'fixation_durations_correct': fixation_durations_correct,
        'fixation_counts_incorrect': fixation_counts_incorrect,
        'fixation_durations_incorrect': fixation_durations_incorrect,
        'fixation_counts_patch': fixation_counts_patch,
        'fixation_durations_patch': fixation_durations_patch,
        'fixation_counts_no_patch': fixation_counts_no_patch,
        'fixation_durations_no_patch': fixation_durations_no_patch
    }, f)

    pd.DataFrame(scarf_segments).to_csv('scarf_plot_input.csv', index=False)

    print(f"All done :) at {datetime.now()}", flush=True)