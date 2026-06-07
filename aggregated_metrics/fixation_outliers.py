
import os
from config import *
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Goal: to identify which fixations are outliers in terms of avg fixations/sec and remove them from the data


ANALYSIS_CSV = '/home/kaia/patchwork_aggregation/timing_correctness_data.csv'

# Init data structures
analysis_df = pd.read_csv(ANALYSIS_CSV)

# don't forget to append file name for this
paths = get_subdirectories()

fixpersec = []

for path in paths:
    pid = os.path.basename(os.path.dirname(path))
    task = os.path.basename(path)
    task_no = task.lstrip("t")
    task_no = np.int64(task_no)
    filename = f"{pid}_{task}_fixation_filtered.csv"
    path = os.path.join(path, filename)
    df = pd.read_csv(path)

    # fixation_group_id is the colname that has fixation IDs
    fixation_ids = np.array(sorted(df['fixation_group_id'].dropna().unique()), dtype=int)

    # get time taken from the analysis csv
    time_taken = analysis_df.loc[(analysis_df['PID'] == pid) & (analysis_df['task_no'] == task_no), 'time_minutes'].values[0]
    time_taken = time_taken * 60  # convert to seconds

    num_fixations = len(fixation_ids)
    fixations_per_sec = num_fixations / time_taken
    fixpersec.append((fixations_per_sec, pid, task_no))

# find stdev of avg fixations/sec 
# subtract 1.5x it from the mean to get lower bound 
mean_fixpersec = np.mean([x[0] for x in fixpersec])
std_fixpersec = np.std([x[0] for x in fixpersec])
lower_bound = mean_fixpersec - 1.5 * std_fixpersec

for fixpersec_value, pid, task_no in fixpersec:
    if fixpersec_value < lower_bound:
        print(f"Fixation outlier detected: PID {pid}, Task {task_no}, Fixations/sec: {fixpersec_value:.2f}")

# Plot histogram of fixations per second
plt.hist([x[0] for x in fixpersec], bins=20, edgecolor='black')
plt.axvline(lower_bound, color='red', linestyle='dashed', linewidth=1)
plt.xlabel('Fixations per Second')
plt.ylabel('Frequency')
plt.title('Histogram of Fixations per Second')

# save the plot
plt.savefig('fixations_per_second_histogram.png')
