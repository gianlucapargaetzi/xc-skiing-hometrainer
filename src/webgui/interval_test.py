import yaml
import matplotlib.pyplot as plt
import numpy as np
from IntensityController.IntervallIntensityController import IntervallParser
# def parse_yaml(filename):
#     with open(filename, 'r') as file:
#         data = yaml.safe_load(file)
#     return data

# def generate_block(data, block_name):
#     block_data = data.get(block_name, {})
#     time = []
#     intensity = []
#     current_time = 0

#     if block_data.get('type') == 'duration_block':
#         duration = block_data['duration']
#         start_intensity = block_data['intensity_start']
#         end_intensity = block_data['intensity_end']
        
#         time.extend(np.linspace(current_time, current_time + duration, num=100))
#         intensity.extend(np.linspace(start_intensity, end_intensity, num=100))
#         current_time += duration
#         last_intensity = end_intensity  # Save end intensity for potential transitions
    
#     elif block_data.get('type') == 'interval_block':
#         on_duration = block_data['on_duration']
#         on_intensity = block_data['on_intensity']
#         off_duration = block_data['off_duration']
#         off_intensity = block_data['off_intensity']
#         block_amount = block_data['block_amount']
#         interval_transition = block_data.get('transition', {'type': 'None', 'length': 0})
#         last_intensity = off_intensity  # Default end intensity after each cycle

#         for _ in range(block_amount):
#             # On period
#             time.extend(np.linspace(current_time, current_time + on_duration, num=50))
#             intensity.extend([on_intensity] * 50)
#             current_time += on_duration

#             # Transition within interval block, if specified
#             if interval_transition['type'] != 'None' and interval_transition['length'] > 0:
#                 trans_length = interval_transition['length']
#                 if interval_transition['type'] == 'linear':
#                     time.extend(np.linspace(current_time, current_time + trans_length, num=50))
#                     intensity.extend(np.linspace(on_intensity, off_intensity, num=50))
#                 elif interval_transition['type'] == 'step':
#                     time.extend(np.linspace(current_time, current_time + trans_length, num=50))
#                     intensity.extend([on_intensity] * 50)
#                 current_time += trans_length

#             # Off period
#             time.extend(np.linspace(current_time, current_time + off_duration, num=50))
#             intensity.extend([off_intensity] * 50)
#             current_time += off_duration

#     elif block_data.get('type') == 'transition':
#         trans_type = block_data['curve']
#         trans_length = block_data['length']
#         start_intensity = intensity[-1] if intensity else 0  # Last intensity from previous block
#         end_intensity = data.get(next_block, {}).get('intensity_start', 0)  # Start intensity of next block if defined

#         if trans_type == 'linear':
#             time.extend(np.linspace(current_time, current_time + trans_length, num=50))
#             intensity.extend(np.linspace(start_intensity, end_intensity, num=50))
#         elif trans_type == 'step':
#             time.extend(np.linspace(current_time, current_time + trans_length, num=50))
#             intensity.extend([start_intensity] * 50)
#         current_time += trans_length

#     return time, intensity

# def plot_block(time, intensity, block_name):
#     plt.figure(figsize=(10, 6))
#     plt.plot(time, intensity, label=f'{block_name} Intensity')
#     plt.xlabel('Time (s)')
#     plt.ylabel('Intensity')
#     plt.title(f'Intensity Curve for {block_name}')
#     plt.legend()
#     plt.grid(True)
#     plt.show()

# # Main script to load YAML data, parse specific block, and plot
# yaml_data = parse_yaml('intervall.yaml')  # Replace 'config.yaml' with your YAML filename

# # Specify which block to plot
# block_name = 'first_block'  # Change this to plot a different block
# time, intensity = generate_block(yaml_data, block_name)
# plot_block(time, intensity, block_name)

# # To print the details of a specific block:
# print(yaml_data.get(block_name, "Block not found"))
IntervallParser("intervall.yaml")