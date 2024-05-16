from pysr import PySRRegressor
import torch 
import torch.nn as nn
import numpy as np
from scm_complex_dataset import scm_dataset_gen, scm_out_of_domain, scm_diff_seed, scm_diff_model, scm_diff_rand_model, scm_indep_ood, scm_normal_dist, scm_indep
from scm_intv_complex_dataset import scm_intv_dataset_gen, scm_intv_ood, scm_intv_c_d_dataset_gen
from torch.optim import Adam
from tqdm import tqdm
from torch.utils.data import Dataset
import torch.nn.init as init
from lime import lime_tabular
from sklearn.preprocessing import MinMaxScaler
from scm_complex_network import MyDataset, DeepModel, TestModel
import os
import dill

import sklearn
import shap

torch.manual_seed(2)
np.random.seed(2)

Scaling = False
Deep = True

Intervene = True 
C_D = False
Independent = False
Simplify = False

#Output_var = 'y1'
Output_var = 'y2'

n_datapoints = 3000
input_scaler = MinMaxScaler()
output_scaler = MinMaxScaler()

if Intervene:
    if C_D:
        inputs, outputs = scm_intv_c_d_dataset_gen(n_datapoints)
    else:
        inputs, outputs = scm_intv_dataset_gen(n_datapoints)

elif Independent:
    inputs, outputs = scm_indep(n_datapoints)
else:
    inputs, outputs = scm_dataset_gen(n_datapoints)


batch_size = 32

#Make torch dataset
input_tensor = torch.from_numpy(inputs).float()
output_tensor = torch.from_numpy(outputs).float()


torch_dataset = MyDataset(input_tensor, output_tensor, Output_var, Simplify) 
# This implicitly shuffles the data as well, do don't need to include that in the dataset generator for the interventional data
train_data, val_data, test_data = torch.utils.data.random_split(torch_dataset, [int(0.7*n_datapoints), int(0.15*n_datapoints), int(0.15*n_datapoints)])  

if Scaling:
    trained_scaler_inputs = torch_dataset.fit_scaling_inputs(input_scaler, train_data)
    trained_scaler_outputs = torch_dataset.fit_scaling_outputs(output_scaler, train_data)


#train_loader = torch.utils.data.DataLoader(train_data, batch_size=batch_size, shuffle = True)
#val_loader = torch.utils.data.DataLoader(val_data, batch_size = 1, shuffle = True)
#test_loader = torch.utils.data.DataLoader(test_data, batch_size = 1, shuffle = True)



### Define an out-of-domain dataset
n_ood = 500

if Intervene:
    ood_inputs, ood_targets = scm_intv_ood(n_ood)
elif Independent:
    ood_inputs, ood_targets = scm_indep_ood(n_ood)
else:
    ood_inputs, ood_targets = scm_out_of_domain(n_ood)

input_tensor = torch.from_numpy(ood_inputs).float()
output_tensor = torch.from_numpy(ood_targets).float()

ood_torch_dataset = MyDataset(input_tensor, output_tensor, Output_var, Simplify) 
if Scaling:
    ood_torch_dataset.scale_inputs(trained_scaler_inputs)
    ood_torch_dataset.scale_outputs(trained_scaler_outputs)
#ood_test_loader = torch.utils.data.DataLoader(ood_torch_dataset, batch_size = 1, shuffle = True)


### Define a dataset with different SCM between the inputs
#For now, this is never interventional 

n_diff_model = 500
diff_mod_inputs, diff_mod_targets = scm_diff_model(n_diff_model)

input_tensor = torch.from_numpy(diff_mod_inputs).float()
output_tensor = torch.from_numpy(diff_mod_targets).float()

diff_mod_torch_dataset = MyDataset(input_tensor, output_tensor, Output_var, Simplify) 
if Scaling:
    diff_mod_torch_dataset.scale_inputs(trained_scaler_inputs)
    diff_mod_torch_dataset.scale_outputs(trained_scaler_outputs)
#diff_mod_loader = torch.utils.data.DataLoader(diff_mod_torch_dataset, batch_size = 1, shuffle = True)


### Define a dataset with different SCM between the inputs, here the inputs are independent of each other
#For now, this is never interventional 

n_diff_rand_model = 500
diff_rand_mod_inputs, diff_rand_mod_targets = scm_diff_rand_model(n_diff_rand_model)

input_tensor = torch.from_numpy(diff_rand_mod_inputs).float()
output_tensor = torch.from_numpy(diff_rand_mod_targets).float()

diff_mod_rand_torch_dataset = MyDataset(input_tensor, output_tensor, Output_var, Simplify) 
if Scaling:
    diff_mod_rand_torch_dataset.scale_inputs(trained_scaler_inputs)
    diff_mod_rand_torch_dataset.scale_outputs(trained_scaler_outputs)
#diff_mod_rand_loader = torch.utils.data.DataLoader(diff_mod_rand_torch_dataset, batch_size = 1, shuffle = True)


#Define a dataset with interventional data, using a different seed from the training
n_intv_testing = 500
intv_inputs, intv_targets = scm_intv_dataset_gen(n_intv_testing, seed = 54321)

input_tensor = torch.from_numpy(intv_inputs).float()
output_tensor = torch.from_numpy(intv_targets).float()

intv_torch_dataset = MyDataset(input_tensor, output_tensor, Output_var, Simplify) 
if Scaling:
    intv_torch_dataset.scale_inputs(trained_scaler_inputs)
    intv_torch_dataset.scale_outputs(trained_scaler_outputs)
intv_test_loader = torch.utils.data.DataLoader(intv_torch_dataset, batch_size = 1, shuffle = True)



def true_model(X):
    A = X[:,0]
    D = X[:, 3]
    E = X[:, 4]

    y1 = 3.5*A + 0.5*D
    y2 = -2*D + 0.2*E

    if Output_var == 'y1':
        return y1
    else: 
        return y2


feature_names = ['a', 'b', 'c', 'd', 'e']


test_input, test_output = test_data[:]
test_input = np.asarray(test_input.numpy())
test_output = np.asarray(test_output.numpy())


intv_input, intv_output = intv_torch_dataset[:]
intv_input = np.asarray(intv_input.numpy())
intv_output = np.asarray(intv_output.numpy())


model = PySRRegressor(
    niterations=10,  # < Increase me for better results
    binary_operators=["+", "-", "*", "/", "^"],
    unary_operators=[
        "cos",
        "exp",
        "sin",
        "square",
        "inv(x) = 1/x",
        # ^ Custom operator (julia syntax)
    ],
    extra_sympy_mappings={"inv": lambda x: 1 / x},
    # ^ Define operator for SymPy as well
    equation_file = "pysr/y1/test.csv",
    # tempdir = "pysr/y1/temp",
    # temp_equation_file = True,
    # delete_tempfiles = False
)


model.fit(intv_input, intv_output, variable_names = feature_names)

symb = model.sympy()


print(model)