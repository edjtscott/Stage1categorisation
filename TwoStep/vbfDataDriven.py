#usual imports
import numpy as np
import pandas as pd
import xgboost as xg
import uproot as upr
import pickle
from sklearn.metrics import roc_auc_score, roc_curve
from os import path, system
from addRowFunctions import truthVBF, vbfWeight, cosThetaStar
from os import listdir

#configure options
from optparse import OptionParser
parser = OptionParser()
parser.add_option('-t','--trainDir', help='Directory for input files')
parser.add_option('-d','--dataFrame', default=None, help='Path to dataframe if it already exists')
parser.add_option('--intLumi',type='float', default=35.9, help='Integrated luminosity')
parser.add_option('--trainParams',default=None, help='Comma-separated list of colon-separated pairs corresponding to parameters for the training')
(opts,args)=parser.parse_args()

#setup global variables
trainDir = opts.trainDir
if trainDir.endswith('/'): trainDir = trainDir[:-1]
frameDir = trainDir.replace('trees','frames')
if opts.trainParams: opts.trainParams = opts.trainParams.split(',')

#define variables to be used
from variableDefinitions import allVarsGen, dijetVars, allVarsGenOld, lumiDict

#including the full selection
hdfQueryString = '(dipho_mass>100.) and (dipho_mass<180.) and (dipho_lead_ptoM>0.333) and (dipho_sublead_ptoM>0.25) and (dijet_LeadJPt>40.) and (dijet_SubJPt>30.) and (dijet_Mjj>250.)'
queryString = '(dipho_mass>100.) and (dipho_mass<180.) and (dipho_leadIDMVA>-0.2) and (dipho_subleadIDMVA>-0.2) and (dipho_lead_ptoM>0.333) and (dipho_sublead_ptoM>0.25) and (dijet_LeadJPt>40.) and (dijet_SubJPt>30.) and (dijet_Mjj>250.)'

#define hdf input
hdfDir = trainDir.replace('trees','hdfs')

hdfList = []
if hdfDir.count('all'):
  for year in lumiDict.keys():
    tempHdfFrame = pd.read_hdf('%s/VBF_with_DataDriven_%s_MERGEDFF_NORM.h5'%(hdfDir,year)).query(hdfQueryString)
    tempHdfFrame = tempHdfFrame[tempHdfFrame['sample']=='QCD']
    tempHdfFrame.loc[:, 'weight'] = tempHdfFrame['weight'] * lumiDict[year]
    tempHdfFrame['HTXSstage1p1bin'] = 0
    hdfList.append(tempHdfFrame)
  hdfFrame = pd.concat(hdfList, sort=False)
else:
  hdfFrame = pd.read_hdf('%s/ThreeClass_with_DataDriven_%s.h5'%(hdfDir,hdfDir.split('/')[-2]) ).query(hdfQueryString)
  hdfFrame = hdfFrame[hdfFrame['sample']=='QCD']
  hdfFrame['HTXSstage1p1bin'] = 0

hdfFrame['proc'] = 'datadriven'
print 'ED DEBUG sum of datadriven weights %.3f'%np.sum(hdfFrame['weight'].values)

#define input files
procFileMap = {'ggh':'powheg_ggH.root', 'vbf':'powheg_VBF.root', 'vh':'powheg_VH.root',
               'dipho':'Dipho.root'}
theProcs = procFileMap.keys()
signals     = ['ggh','vbf','vh']
backgrounds = ['dipho']

#either get existing data frame or create it
trainTotal = None
if not opts.dataFrame:
  trainList = []
  #get trees from files, put them in data frames
  if not 'all' in trainDir:
    for proc,fn in procFileMap.iteritems():
      print 'reading in tree from file %s'%fn
      trainFile   = upr.open('%s/%s'%(trainDir,fn))
      if proc in signals: trainTree = trainFile['vbfTagDumper/trees/%s_125_13TeV_GeneralDipho'%proc]
      elif proc in backgrounds: trainTree = trainFile['vbfTagDumper/trees/%s_13TeV_GeneralDipho'%proc]
      else: raise Exception('Error did not recognise process %s !'%proc)
      if proc in signals:  
          tempFrame = trainTree.pandas.df(allVarsGen).query(queryString)
          tempFrame['cosThetaStar'] = tempFrame.apply(cosThetaStar, axis=1)
      elif proc in backgrounds:  
          tempFrame = trainTree.pandas.df(allVarsGenOld).query(queryString)
          tempFrame['HTXSstage1p1bin'] = 0
      tempFrame['proc'] = proc
      trainList.append(tempFrame)
  else:
    for year in lumiDict.keys():
      for proc,fn in procFileMap.iteritems():
        thisDir = trainDir.replace('all',year)
        print 'reading in tree from file %s'%fn
        trainFile   = upr.open('%s/%s'%(thisDir,fn))
        if proc in signals: trainTree = trainFile['vbfTagDumper/trees/%s_125_13TeV_GeneralDipho'%proc]
        elif proc in backgrounds: trainTree = trainFile['vbfTagDumper/trees/%s_13TeV_GeneralDipho'%proc]
        else: raise Exception('Error did not recognise process %s !'%proc)
        if proc in signals:  
            tempFrame = trainTree.pandas.df(allVarsGen).query(queryString)
            tempFrame['cosThetaStar'] = tempFrame.apply(cosThetaStar, axis=1)
        elif proc in backgrounds:  
            tempFrame = trainTree.pandas.df(allVarsGenOld).query(queryString)
            tempFrame['HTXSstage1p1bin'] = 0
        tempFrame['proc'] = proc
        tempFrame.loc[:, 'weight'] = tempFrame['weight'] * lumiDict[year]
        trainList.append(tempFrame)
  print 'got trees and applied selections'

  #create one total frame
  trainList.append(hdfFrame)
  trainTotal = pd.concat(trainList, sort=False)
  del trainList
  del hdfFrame
  del tempFrame
  print 'created total frame'

  #add the target variable and the equalised weight
  trainTotal['truthVBF'] = trainTotal.apply(truthVBF,axis=1)
  trainTotal = trainTotal[trainTotal.truthVBF>-0.5]
  vbfSumW = np.sum(trainTotal[trainTotal.truthVBF==2]['weight'].values)
  gghSumW = np.sum(trainTotal[trainTotal.truthVBF==1]['weight'].values)
  bkgSumW = np.sum(trainTotal[trainTotal.truthVBF==0]['weight'].values)
  print 'ED DEBUG bkgSumW = %.3f'%bkgSumW
  trainTotal['vbfWeight'] = trainTotal.apply(vbfWeight, axis=1, args=[vbfSumW,gghSumW,bkgSumW])
  trainTotal['dijet_centrality']=np.exp(-4.*((trainTotal.dijet_Zep/trainTotal.dijet_abs_dEta)**2))

  #save as a pickle file
  if not path.isdir(frameDir): 
    system('mkdir -p %s'%frameDir)
  trainTotal.to_pickle('%s/vbfDataDriven.pkl'%frameDir)
  print 'frame saved as %s/vbfDataDriven.pkl'%frameDir

#read in dataframe if above steps done before
else:
  trainTotal = pd.read_pickle('%s/%s'%(frameDir,opts.dataFrame))
  print 'Successfully loaded the dataframe'

#set up train set and randomise the inputs
trainFrac = 0.8
theShape = trainTotal.shape[0]
theShuffle = np.random.permutation(theShape)
trainLimit = int(theShape*trainFrac)

#define the values needed for training as numpy arrays
vbfX  = trainTotal[dijetVars].values
vbfY  = trainTotal['truthVBF'].values
vbfTW = trainTotal['vbfWeight'].values
vbfFW = trainTotal['weight'].values
vbfM  = trainTotal['dipho_mass'].values

#do the shuffle
vbfX  = vbfX[theShuffle]
vbfY  = vbfY[theShuffle]
vbfTW = vbfTW[theShuffle]
vbfFW = vbfFW[theShuffle]
vbfM  = vbfM[theShuffle]

#split into train and test
vbfTrainX,  vbfTestX  = np.split( vbfX,  [trainLimit] )
vbfTrainY,  vbfTestY  = np.split( vbfY,  [trainLimit] )
vbfTrainTW, vbfTestTW = np.split( vbfTW, [trainLimit] )
vbfTrainFW, vbfTestFW = np.split( vbfFW, [trainLimit] )
vbfTrainM,  vbfTestM  = np.split( vbfM,  [trainLimit] )

#set up the training and testing matrices
trainMatrix = xg.DMatrix(vbfTrainX, label=vbfTrainY, weight=vbfTrainTW, feature_names=dijetVars)
testMatrix  = xg.DMatrix(vbfTestX, label=vbfTestY, weight=vbfTestFW, feature_names=dijetVars)
trainParams = {}
trainParams['objective'] = 'multi:softprob'
numClasses = 3
trainParams['num_class'] = numClasses
trainParams['nthread'] = 1
#trainParams['seed'] = 123456

#add any specified training parameters
paramExt = ''
if opts.trainParams:
  paramExt = '__'
  for pair in opts.trainParams:
    key  = pair.split(':')[0]
    data = pair.split(':')[1]
    trainParams[key] = data
    paramExt += '%s_%s__'%(key,data)
  paramExt = paramExt[:-2]

#train the BDT
print 'about to train diphoton BDT'
vbfModel = xg.train(trainParams, trainMatrix)
print 'done'

#save it
modelDir = trainDir.replace('trees','models')
if not path.isdir(modelDir):
  system('mkdir -p %s'%modelDir)
vbfModel.save_model('%s/vbfDataDriven%s.model'%(modelDir,paramExt))
print 'saved as %s/vbfDataDriven%s.model'%(modelDir,paramExt)

#evaluate performance using area under the ROC curve
vbfPredYtrain = vbfModel.predict(trainMatrix).reshape(vbfTrainY.shape[0],numClasses)
vbfPredYtest  = vbfModel.predict(testMatrix).reshape(vbfTestY.shape[0],numClasses)
vbfTruthYtrain = np.where(vbfTrainY==2, 0, 1)
vbfTruthYtest  = np.where(vbfTestY==2, 0, 1)
print 'Training performance:'
print 'area under roc curve for training set = %1.3f'%( 1.-roc_auc_score(vbfTruthYtrain, vbfPredYtrain[:,2], sample_weight=vbfTrainFW) )
print 'area under roc curve for test set     = %1.3f'%( 1.-roc_auc_score(vbfTruthYtest,  vbfPredYtest[:,2],  sample_weight=vbfTestFW)  )