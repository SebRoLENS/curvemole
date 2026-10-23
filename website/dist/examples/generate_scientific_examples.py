"""Generate website figures with the real CurveMole Python engine.
Run with CurveMole 0.46.0 installed: python scripts/generate_scientific_examples.py
Synthetic data; independent Gaussian noise; supplied sigma_y; absolute_sigma=True.
"""
from pathlib import Path
import argparse, json, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from curvemole import Curve, Component, Project, Fitter, FitSettings, default_registry, __version__
from curvemole.core.functions import formula_definition
from curvemole.core.serialization import save_project, load_project
from curvemole.core.data import CurveState
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=Path.cwd()/'curvemole-examples')
OUT=parser.parse_args().output; OUT.mkdir(parents=True,exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'text.color':'#b8c8d6','axes.labelcolor':'#b8c8d6','xtick.color':'#94a9ba','ytick.color':'#94a9ba','axes.edgecolor':'#405161','axes.facecolor':'#111c27','figure.facecolor':'#111c27','svg.fonttype':'none'})
rng=np.random.default_rng(20261022)
all_data=[]; summaries=[]
for key in ['spectrum','oscillation','kinetics']:
    project=Project('CurveMole scientific example: '+key)
    if key=='spectrum':
        title='Two Gaussians + linear term'; xlabel='x'; ylabel='y'
        x=np.linspace(600,1400,90); sigma=.025+.018*(x-x.min())/np.ptp(x)
        def gauss(x,a,c,s): return a*np.exp(-.5*((x-c)/s)**2)/(s*np.sqrt(2*np.pi))
        truth=.12+.00013*x+gauss(x,110,880,44)+gauss(x,145,1000,65)
        components=[Component.create('linear',name='Background',initial={'intercept':.1,'slope':.0001}),Component.create('gaussian',name='Band 1',initial={'area':100,'center':865,'sigma':42}),Component.create('gaussian',name='Band 2',initial={'area':130,'center':1020,'sigma':60})]
        components[0].is_background=True
        for c in components[1:]:
            c.parameters['area'].minimum=0;c.parameters['center'].minimum=700;c.parameters['center'].maximum=1200;c.parameters['sigma'].minimum=5;c.parameters['sigma'].maximum=150
        formula='Linear background + two area-normalized Gaussian bands'
    else:
        if key=='oscillation':
            title='Exponentially damped cosine'; xlabel='x'; ylabel='y'
            x=np.linspace(0,12,85);sigma=.038+.022*x/12
            formula='offset + A*exp(-x/tau)*cos(omega*x + phi)'
            truth=.18+1.25*np.exp(-x/5.2)*np.cos(2.5*x+.3)
            initial={'offset':.15,'A':1.1,'tau':4.5,'omega':2.45,'phi':.2}
            bounds={'A':(0,3),'tau':(.2,20),'omega':(1.8,3.2),'phi':(-3.14,3.14),'offset':(-1,1)}
        else:
            title='Difference of exponentials'; xlabel='x'; ylabel='y'
            x=np.linspace(0,16,75);sigma=.025+.035*x/16
            formula='offset + A*(exp(-k_slow*x) - exp(-k_fast*x))'
            truth=.1+2.4*(np.exp(-.16*x)-np.exp(-1.05*x))
            initial={'offset':.08,'A':2.1,'k_slow':.14,'k_fast':.9}
            bounds={'offset':(-.3,.5),'A':(.1,5),'k_slow':(.02,.4),'k_fast':(.5,2)}
        definition=formula_definition('site_'+key,title,formula,defaults=initial,bounds=bounds)
        default_registry().register(definition,replace=True)
        project.custom_functions.append({'identifier':definition.identifier,'display_name':definition.display_name,'kind':definition.kind,**definition.custom_metadata})
        components=[Component.create(definition.identifier,initial=initial)]
    y=truth+rng.normal(0,sigma)
    curve=Curve(title,x,y,sigma_y=sigma,x_label=xlabel,y_label=ylabel,source='Synthetic website example; seed 20261022')
    project.add_curve(curve);model=project.model_for(curve.id)
    for c in components:model.add(c)
    result=Fitter().fit_single(curve,model,FitSettings(use_data_errors=True,absolute_sigma=True))
    assert result.success,(key,result.message)
    for path,est in result.parameters.items():
        p=project.parameter_map()[path];p.standard_error=est.standard_error;p.ci_low=est.ci_low;p.ci_high=est.ci_high
    curve.state=CurveState.FITTED;project.results['last_fit']=result;project.results['fit:'+curve.id]=result
    xx=np.linspace(x.min(),x.max(),650); yy,parts=model.evaluate(xx,components=True)
    fitted=model.evaluate(x); residual=(y-fitted)/sigma
    dof=len(x)-len(result.free_parameter_paths); chi=float(np.sum(residual**2)/dof)
    assert np.allclose(fitted,result.curve_outputs[curve.id].fitted)
    fig,(ax,ar)=plt.subplots(2,1,figsize=(9,5.5),sharex=True,gridspec_kw={'height_ratios':[3.3,1],'hspace':.13})
    fig.subplots_adjust(left=.11,right=.97,bottom=.12,top=.89)
    ax.errorbar(x,y,yerr=sigma,fmt='o',ms=3.1,color='#d8e5ec',ecolor='#8da6b8',elinewidth=.8,capsize=2,capthick=.8,label='Synthetic data ±1σ',zorder=3)
    ax.plot(xx,yy,color='#9bf3cd',lw=2,label='CurveMole fit',zorder=4)
    if key=='spectrum':
        bg=parts[components[0].id]
        for c,col in zip(components[1:],['#bca9f6','#eeb886']):ax.plot(xx,parts[c.id]+bg,'--',color=col,lw=1.2,label=c.name+' + background')
    ax.set_ylabel(ylabel);ax.set_title(title,loc='left',color='#edf3f4',fontsize=15,pad=15)
    ax.legend(loc='upper right',fontsize=8,facecolor='#111c27',edgecolor='none',labelcolor='#b8c8d6')
    ax.text(.99,1.04,f'N = {len(x)}   ·   χ²ᵣ = {chi:.2f}',transform=ax.transAxes,ha='right',fontsize=10,color='#9bf3cd')
    ar.axhspan(-2,2,color='#9bf3cd',alpha=.04);ar.axhline(0,color='#8ca3b1',lw=.8)
    ar.plot(x,residual,'o',ms=3,color='#b8c8d6');ar.set_ylabel('(y − fit)/σ',fontsize=9);ar.set_xlabel(xlabel);ar.set_ylim(-3.8,3.8);ar.set_yticks([-3,0,3])
    for a in [ax,ar]:
        a.spines[['top','right']].set_visible(False);a.grid(alpha=.08);a.tick_params(labelsize=9)
    fig.savefig(OUT/(key+'.svg'));plt.close(fig)
    np.savetxt(OUT/(key+'.csv'),np.column_stack([x,y,sigma,fitted,residual]),delimiter=',',header='x,y,sigma_y,fit,normalized_residual',comments='')
    save_project(project,OUT/(key+'.fitproj'))
    restored=load_project(OUT/(key+'.fitproj'));assert len(restored.curves)==1
    assert np.allclose(restored.model_for(restored.curves[0].id).evaluate(x),fitted)
    pars=[{'component':c.name,'name':name,'value':p.value,'standard_error':p.standard_error,'ci_low':p.ci_low,'ci_high':p.ci_high} for c in components for name,p in c.parameters.items()]
    summary={'key':key,'title':title,'engine':'CurveMole '+__version__,'formula':formula,'N':len(x),'dof':dof,'reduced_chi_square':chi,'parameters':pars,'settings':{'use_data_errors':True,'absolute_sigma':True,'loss':'linear'},'warnings':result.warnings}
    (OUT/(key+'-fit.json')).write_text(json.dumps(summary,indent=2));summaries.append(summary)
    all_data.append({'key':key,'title':title,'xlabel':xlabel,'ylabel':ylabel,'x':x.tolist(),'y':y.tolist(),'sigma':sigma.tolist(),'xx':xx.tolist(),'fit':yy.tolist(),'chi':round(chi,2)})
    print(key,'success',chi,'warnings',result.warnings)
(OUT/'results.json').write_text(json.dumps(summaries,indent=2))
(OUT/'data.js').write_text('const scientificExamples = '+json.dumps(all_data,separators=(',',':'))+';\n')
