from dallinger.experiments import Griduniverse
import multiprocessing
from datetime import datetime
import random

def parse_save_links():
    file_path = "save_links.txt"
    temp_file_path = "temp_save_links.txt"

    # Create a temporary file
    open(temp_file_path, 'w').close()

    # Open the original file for reading and the temporary file for writing
    with open(file_path, 'r') as original_file, open(temp_file_path, 'w') as temp_file:
        # Read each line from the original file
        for line in original_file:
            # Check if the line starts with "Single"
            if line.strip().startswith("Single"):
                # If it does, write the line to the temporary file
                temp_file.write(line)

    # Replace the original file with the temporary file
    import os
    os.replace(temp_file_path, file_path)

    # Delete the temporary file
    os.remove(temp_file_path)

    print("Processing complete.")


def run_experiment(iteration, participants, app_name):
    experiment = Griduniverse()
    print("before ran")
    others = True
    chat = True
    
    data = experiment.run(
        mode="sandbox",
        max_participants=participants,
        num_dynos_worker=participants +1,
        others_visible=others,
        show_chatroom=chat,
        id=app_name,
    )
    print("ran")
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"Experiment_Data/DataTrial-experiment-{now}-{iteration}.csv"
    experiment.save_data_to_file(data, filename)

participants = 2
iterations = 5

# Create a pool of processes
pool = multiprocessing.Pool(processes=iterations)

# Launch experiments in parallel
results = []
for i in range(iterations):
    app_name = "dlgr-amdahl-5pies10sec" + str(i)
    results.append(pool.apply_async(run_experiment, args=(i, participants, app_name)))

# Close the pool and wait for all processes to complete
pool.close()
pool.join()

print("All experiments completed.")