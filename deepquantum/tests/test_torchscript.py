# -*- coding: utf-8 -*-
"""
Created on Mon Nov 29 09:47:57 2021

@author: shish
用于测试模型是否可以被转成torchscript中间层的.pt文件
1-torchscript对多重继承不支持，父类的静态方法，子类无法用self.的方式调用，必须用父类名.的方式调用
2-torchscript可能对函数的输入变量类型推断错误，报错之处要手动指定python数据类型
3-torchscript不支持类的属性，只支持实例属性
4-列表中的元素必须类型一致
5-torchscript只支持python的math库，其他库不支持
6-要使用脚本模式，请确保从torch.jit.ScriptModule基类（而不是torch.nn.Module）继承
"""
import torch
import torch.nn as nn
import torch.optim as optim
import matplotlib.pyplot as plt
import random
import math



from deepquantum.gates.qmath import multi_kron, measure, IsUnitary, IsNormalized
import deepquantum.gates.qoperator as op
from deepquantum.gates.qcircuit import Circuit
from deepquantum.embeddings.qembedding import PauliEncoding
from deepquantum.layers.qlayers import XYZLayer, YZYLayer, ZXLayer,ring_of_cnot, ring_of_cnot2, BasicEntangleLayer






#==============================================================================
class qcir(torch.jit.ScriptModule):
    def __init__(self,nqubits):
        super().__init__()
        #属性：量子线路qubit数目，随机初始化的线路参数，测量力学量列表
        self.nqubits = nqubits
        self.weight = \
            nn.Parameter( nn.init.uniform_(torch.empty(11*self.nqubits), a=0.0, b=2*torch.pi) )
        
        self.M_lst = self.Zmeasure()

        
    def Zmeasure(self):
        #生成测量力学量的列表
        M_lst = []
        for i in range(self.nqubits):
            Mi = op.PauliZ(self.nqubits,i).U_expand()
            M_lst.append( Mi )
        
        return M_lst
            
    
    def build_circuit(self,input_lst_batch):
        '''
        构建变分量子线路的演化矩阵
        '''
        wires_lst = [i for i in range(self.nqubits)]
        #创建线路
        c1 = Circuit(self.nqubits) 
        
        #encoding编码部分
        batch_size = len(input_lst_batch)
        phi_encoded_batch = torch.zeros( batch_size, 2**self.nqubits) + 0j
        for i, inputs in enumerate(input_lst_batch):
            e = PauliEncoding(self.nqubits, inputs, wires_lst,pauli='Y')
            E = e.U_expand() #编码矩阵
            phi_encoded_batch[i] = E @ c1.state_init() #矩阵与列向量相乘
        
        #variation变分部分
        c1.PauliX(0)
        c1.PauliY(1)
        c1.PauliZ(0)
        c1.Hadamard(1)
        c1.rxx(0.3,[1,0])
        c1.ryy(0.2,[1,2])
        c1.rzz(0.4,[2,0])
        c1.SWAP([0,2])
        c1.add( BasicEntangleLayer(self.nqubits, wires_lst, self.weight[0*self.nqubits:3*self.nqubits]) )
        # c1.add( BasicEntangleLayer(self.nqubits, wires_lst, self.weight[3*self.nqubits:6*self.nqubits]) )
        c1.add( XYZLayer(self.nqubits, wires_lst, self.weight[6*self.nqubits:9*self.nqubits]) )
        c1.add( ring_of_cnot2(self.nqubits, wires_lst) )
        # c1.add( YZYLayer(self.nqubits, wires_lst, self.weight[9*self.nqubits:12*self.nqubits]) )
        # c1.add( ring_of_cnot2(self.nqubits, wires_lst) )
        c1.ZXLayer( wires_lst, self.weight[9*self.nqubits:11*self.nqubits] ) 
        c1.ring_of_cnot(wires_lst)
        c1.toffoli([2,1,0])
        
        #U = c1.U()
        print([each.info()['label'] for each in c1.gate ])
        #最终返回线路变分部分的 演化酉矩阵 和 编码后的态矢
        #return U + 0j, phi_encoded_batch.permute(1,0)
        return c1, phi_encoded_batch.permute(1,0)
    
    #@torch.jit.script_method
    def forward(self,input_lst_batch):
        #计算编码后的态和变分线路的演化矩阵
        c1, phi_encoded_batch = self.build_circuit(input_lst_batch)
        U = c1.U()
        #计算线路演化终态
        phi_out = U @ phi_encoded_batch # 8 X batch_size
        
        #模拟测量得到各个测量力学量的期望值
        measure_rst = []
        for Mi in self.M_lst: 
            measure_rst.append( measure(phi_out, Mi) )
        
        #以3个qubit的线路为例，把3个[batch,1]的矩阵拼接为[batch,3]
        rst = torch.cat( tuple(measure_rst),dim=1 ) 
        
        #把值域做拉伸，从[-1,1]变为[-4,4]
        rst = ( rst + 0 ) * 4
        return rst
        
        # rst_average = rst[:,0]
        # for i in range(1,rst.shape[1]):
        #     rst_average += rst[:,i]
        
        # rst_average = rst_average * (1.0/rst.shape[1])
            
        # return rst_average.view(-1,1)
        
        
        
#torch.jit.ScriptModule也是继承自nn.Module
#若要转成torchscript中间层所有相关模块必须继承自torch.jit.ScriptModule
class qnet(torch.jit.ScriptModule):
    
    def __init__(self,nqubits):
        super().__init__()
        
        #self.nqubits = nqubits
        self.circuit = qcir(nqubits)
        self.FC1 = nn.Linear(len(self.circuit.M_lst),8)
        #self.FC1 = nn.Linear(1,8)
        self.FC2 = nn.Linear(8,8)
        self.FC3 = nn.Linear(8,1)
      
   
    #@torch.jit.script_method
    def forward(self,x_batch):
        
        pre_batch = x_batch + torch.tensor(0.0)
        
        cir_out = self.circuit ( pre_batch )
        
        #return cir_out[:,0]
        out = nn.functional.leaky_relu(self.FC1(cir_out))
        #out = nn.functional.leaky_relu(self.FC1(pre_batch))
        out = nn.functional.leaky_relu(self.FC2(out))
        out = nn.functional.leaky_relu(self.FC3(out))
        return out





def foo(x1):
    y = 2*math.sin(x1)
    return y




if __name__ == "__main__":
    
    # N = 2
    # num_examples = 512
    # num_inputs = 1
    # num_outputs = 1
    
    # features = torch.empty( num_examples,num_inputs )
    # labels = torch.empty( num_examples,num_outputs )
    # for i in range(num_examples):
    #     features[i] = torch.rand(num_inputs)*2*math.pi

    # for i in range(num_examples):
    #     labels[i] = foo( features[i][0] ) + 1e-3*random.random()
    
    # def data_iter(batch_size, features, labels):
    #     #输入batch_size，输入训练集地数据features+标签labels
    #     num_examples = len(features)
    #     indices = list(range(num_examples))
    #     random.shuffle(indices) #把indices列表顺序随机打乱
    #     for i in range(0,num_examples,batch_size):
    #         #每次取batch_size个训练样本,j代表索引
    #         j = torch.LongTensor( indices[i:min(i+batch_size,num_examples)] ) 
    #         #print(features.index_select(0,j), labels.index_select(0,j))
    #         yield features.index_select(0,j), labels.index_select(0,j)
    #         #把张量沿着0维，只保留取出索引号对应的元素
    
#=============================================================================
    net2 = qnet(4)
    print('推断结果：',net2( torch.tensor([[2.5]]) ))
    print('start producing torchscript file')
    scripted_modeule = torch.jit.script(qnet(4))
    torch.jit.save(scripted_modeule, 'test_torchscript.pt')
    print('completed!')
    #onnx_modeule = qnet(2)
    #onnx.checker.check_model(onnx_modeule)
    #onnx.save(onnx_modeule, 'D:/git')
    '''
    net1 = qnet(N)      #构建训练模型
    loss = nn.MSELoss() #平方损失函数
    
    #定义优化器，也就是选择优化器，选择Adam梯度下降，还是随机梯度下降，或者其他什么
    #optimizer = optim.SGD(net1.parameters(), lr=0.1) #lr为学习率
    optimizer = optim.Adam(net1.parameters(), lr=0.01) #lr为学习率
    
    #lr_scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer,mode='min',factor=0.1,patience=10,verbose=False,
    #                                      threshold=0.0001, threshold_mode='rel',cooldown=0,min_lr=0,eps=1e-6)
    
    #lr_scheduler = optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.9)
    
    lr_scheduler = optim.lr_scheduler.MultiStepLR(optimizer,milestones=[5,10,15], gamma=0.8)
    
    
    
    
    #torch.cuda.set_device(0)
    num_epochs = 30;
    batch_size = 64;
    
    #记录loss随着epoch的变化，用于后续绘图
    epoch_lst = [i+1 for i in range(num_epochs)]
    loss_lst = []
    
    for epoch in range(1,num_epochs+1):
        for x,y in data_iter(batch_size,features,labels):
            
            x.requires_grad_(True)
            output = net1(x);
            #squeeze是为了把y维度从1x3变成3
            l = loss(output.squeeze(),y.squeeze());
            #梯度清0
            optimizer.zero_grad() 
            l.backward()
            #print("weights_grad2:",net1.circuit.weight.grad,'  weight is leaf?:',net1.circuit.weight.is_leaf)
            optimizer.step()
            
        #lr_scheduler.step()
        
        loss_lst.append(l.item())
        print("epoch:%d, loss:%f" % (epoch,l.item()),\
              ';current lr:', optimizer.state_dict()["param_groups"][0]["lr"])
        
        #print(net1.circuit.weight)
    
    
    
    plt.cla()
    plt.subplot(121)
    xx = list(features[:num_examples,0])
    
    yy = [float(each) for each in net1( features[:num_examples,:] ).squeeze() ]
    xx = [float( xi ) for xi in xx]
    yy_t = [foo(xi) for xi in xx]
    plt.plot(xx,yy,'m^',linewidth=1, markersize=2)
    plt.plot(xx,yy_t,'g^',linewidth=1, markersize=0.5)
    
    plt.subplot(122)
    plt.plot(epoch_lst,loss_lst,'r^--',linewidth=1, markersize=1.5)
    plt.show()
    '''
    input("END")
    
































    


 














































































































        