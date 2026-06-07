import warnings
import os
import re

warnings.filterwarnings("ignore")

OUTLIERS = ["/home/kaia/patchwork_data/P10/t2",
            "/home/kaia/patchwork_data/P10/t3",
            "/home/kaia/patchwork_data/P7/t3",
            "/home/kaia/patchwork_data/P28/t3",
            "/home/kaia/patchwork_data/P32/t2",
            "/home/kaia/patchwork_data/P1/t2",
            "/home/kaia/patchwork_data/P1/t3",
            "/home/kaia/patchwork_data/P1/t1",
            "/home/kaia/patchwork_data/P19/t2"]

# project_path = '/Users/klnewman/Desktop/P15'
project_paths = ['/home/kaia/patchwork_data']

def get_subdirectories():
    # Add new code that goes through all directories starting with "P" that do not contain hyphens and adds all paths to tasks to a list
    all_task_paths = []
    for project_path in project_paths:
        items = os.listdir(project_path)
        participant_paths = [os.path.join(project_path, item) for item in items 
                        if os.path.isdir(os.path.join(project_path, item)) and item.startswith('P') and "-" not in item]
        task_paths = []
        for participant_path in participant_paths:
            t1_path = os.path.join(participant_path, 't1')
            t2_path = os.path.join(participant_path, 't2')
            t3_path = os.path.join(participant_path, 't3')

            task_paths.append(t1_path)
            task_paths.append(t2_path)
            task_paths.append(t3_path)

        all_task_paths.extend(task_paths)
    
    # Filter out outliers/ones already visualized/otherwise defunct
    all_task_paths = [path for path in all_task_paths if path not in OUTLIERS]

    return all_task_paths
