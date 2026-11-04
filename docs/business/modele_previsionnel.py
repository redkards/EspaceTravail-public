# Modele du previsionnel SYFER V2 (hypotheses explicites : voir business-plan.md, section 11). Usage : python3 modele_previsionnel.py
import csv, os, json
import pathlib
OUT=str(pathlib.Path(__file__).resolve().parent)  # ecrit les CSV a cote du script
COT=0.256; CFP=0.002; VL=0.022  # BNC SSI 2026, CFP liberal, versement liberatoire (option)
# --- hypotheses par scenario et par annee ---
S={
 "prudent":{
  1:dict(diag=(4,590),pilote=(3,950),inst=(2,1600),maint=99,regie=(15,450),lic=(0,0,0),abo_rate=0.7,mkt=600,ia=5*12,outils=35*12,rc=400,jur=300+15+270,cfe=0,form=150),
  2:dict(diag=(6,690),pilote=(0,0),inst=(5,1800),maint=109,regie=(30,500),lic=(0,0,0),abo_rate=0.7,mkt=900,ia=10*12,outils=40*12,rc=400,jur=15+200,cfe=250,form=200),
  3:dict(diag=(8,690),pilote=(0,0),inst=(7,1900),maint=119,regie=(40,550),lic=(0,0,0),abo_rate=0.7,mkt=1200,ia=15*12,outils=45*12,rc=450,jur=15+300,cfe=300,form=300)},
 "central":{
  1:dict(diag=(8,690),pilote=(3,950),inst=(5,1900),maint=129,regie=(35,520),lic=(0,0,0),abo_rate=0.8,mkt=1200,ia=30*12,outils=50*12,rc=550,jur=270+30+800,cfe=0,form=300),
  2:dict(diag=(12,790),pilote=(0,0),inst=(9,2100),maint=139,regie=(45,560),lic=(1,2000,25),abo_rate=0.8,mkt=2000,ia=40*12,outils=60*12,rc=600,jur=15+400,cfe=300,form=400),
  3:dict(diag=(14,790),pilote=(0,0),inst=(11,2200),maint=149,regie=(45,600),lic=(3,2000,25),abo_rate=0.8,mkt=2500,ia=50*12,outils=70*12,rc=650,jur=15+500,cfe=350,form=500)},
 "ambitieux":{
  1:dict(diag=(14,790),pilote=(3,950),inst=(9,2200),maint=149,regie=(45,580),lic=(0,0,0),abo_rate=0.85,mkt=2400,ia=60*12,outils=70*12,rc=650,jur=270+30+1500,cfe=0,form=500),
  2:dict(diag=(20,890),pilote=(0,0),inst=(15,2400),maint=159,regie=(50,620),lic=(3,2500,30),abo_rate=0.85,mkt=4000,ia=80*12,outils=90*12,rc=700,jur=15+800,cfe=350,form=600),
  3:dict(diag=(25,890),pilote=(0,0),inst=(20,2500),maint=169,regie=(50,650),lic=(8,2500,30),abo_rate=0.85,mkt=6000,ia=100*12,outils=110*12,rc=800,jur=1500+15,cfe=400,form=800)},
}
CHURN=0.20
CAPA=160; TJM_ST=380  # attrition annuelle abonnements
CLIENTS_PER_LIC=5
INFRA={1:550,2:550,3:1060}  # VPS amorti (860 TTC/24 mois) + sauvegardes ; an 3 = prix de renouvellement
MALT_SHARE=0.3; MALT_COM=0.10
# jours de travail par unite (capacite)
J=dict(diag=1.5,pilote=4,inst=3,maint_h=1.5,lic=4)
rows=[]; summary={}
for sc,yrs in S.items():
  subs_end=0.0; summary[sc]={}
  for y in (1,2,3):
    h=yrs[y]
    nd,pd=h["diag"]; np_,pp=h["pilote"]; ni,pi=h["inst"]; nr,tjm=h["regie"]; nl,lf,lc=h["lic"]
    new_subs=(np_+ni)*h["abo_rate"]
    start=subs_end*(1-CHURN)
    # nouveaux abonnes : ~5,5 mois factures l annee d arrivee (an 1 : 6,15 car pilotes en janv-mars)
    mois_new= 6.15 if y==1 else 5.5
    maint=round(start*12*h["maint"]+new_subs*mois_new*h["maint"])
    subs_end=start+new_subs
    lic=round(nl*lf+nl*CLIENTS_PER_LIC*lc*12*0.5)
    ca={ "Diagnostic ECHO":nd*pd, "Pilotes":np_*pp, "Installations Solo":ni*pi, "Maintenance (abonnements)":maint,
         "Agents sur mesure / regie":nr*tjm, "Licences integrateurs":lic}
    CA=sum(ca.values())
    malt=round(nr*tjm*MALT_SHARE*MALT_COM)
    micro = True  # sortie du regime seulement apres 2 annees civiles consecutives de depassement
    cot=round(CA*(COT+CFP)); imp=round(CA*VL)
    ch={ "Infrastructure (VPS, sauvegardes)":INFRA[y], "IA payante plafonnee":h["ia"], "Outils et abonnements":h["outils"],
         "Assurance RC pro":h["rc"], "Juridique (marque, e-Soleau, CGV, societe)":h["jur"], "Marketing":h["mkt"],
         "Commission Malt":malt, "Formation et veille":h["form"], "CFE":h["cfe"] }
    days=nd*J["diag"]+np_*J["pilote"]+ni*J["inst"]+nr+ (start+new_subs/2)*12*J["maint_h"]/7+nl*J["lic"]
    st=max(0,days-CAPA)*TJM_ST
    ch["Sous-traitance (jours au-dela de 160 j/an)"]=round(st)
    CH=sum(ch.values())
    net=CA-CH-cot-imp
    clients=nd+np_+ni
    summary[sc][y]=dict(CA=CA,CH=CH,cot=cot,imp=imp,net=net,days=round(days),subs=round(subs_end,1),clients=clients,micro=micro,ca=ca,ch=ch)
    for k,v in ca.items(): rows.append([sc,f"An {y}","Chiffre d'affaires",k,v])
    rows.append([sc,f"An {y}","Chiffre d'affaires","TOTAL CA HT",CA])
    for k,v in ch.items(): rows.append([sc,f"An {y}","Charges",k,v])
    rows.append([sc,f"An {y}","Charges","TOTAL charges d'exploitation",CH])
    rows.append([sc,f"An {y}","Prelevements","Cotisations sociales 25,6 % + CFP 0,2 % (micro BNC SSI)",cot])
    rows.append([sc,f"An {y}","Prelevements","Impot (versement liberatoire 2,2 % si option)",imp])
    rows.append([sc,f"An {y}","Resultat","Revenu net disponible du dirigeant",round(net)])
    rows.append([sc,f"An {y}","Indicateurs","Revenu net mensuel moyen",round(net/12)])
    rows.append([sc,f"An {y}","Indicateurs","Clients nouveaux (diag+pilotes+installations)",clients])
    rows.append([sc,f"An {y}","Indicateurs","Abonnes maintenance en fin d'annee",round(subs_end,1)])
    rows.append([sc,f"An {y}","Indicateurs","Jours de production estimes",round(days)])
    rows.append([sc,f"An {y}","Indicateurs","Regime","micro-entreprise (TVA due si CA > 37 500 EUR)"])
with open(f"{OUT}/previsionnel_3ans.csv","w",newline="",encoding="utf-8") as f:
  w=csv.writer(f,delimiter=";"); w.writerow(["scenario","annee","bloc","poste","montant_eur"]); w.writerows(rows)
# ---- tresorerie mensuelle an 1 (central) : M0 = nov-dec 2026, M1..M12 = janv-dec 2027
h=S["central"][1]
mois=["M0 nov-dec 2026"]+[f"M{i} {m} 2027" for i,m in enumerate(["janv","fevr","mars","avr","mai","juin","juil","aout","sept","oct","nov","dec"],1)]
plan={ # ventes par mois (index 1..12)
 "diag":[0,1,0,1,1,0,1,0,1,1,1,1,0], "pilote":[0,1,1,1,0,0,0,0,0,0,0,0,0], "inst":[0,0,0,0,1,0,1,0,0,1,1,0,1],
 "regie":[0,0,2,3,3,4,4,2,1,4,4,4,4]}
assert sum(plan["diag"])==h["diag"][0] and sum(plan["inst"])==h["inst"][0] and sum(plan["regie"])==h["regie"][0], (sum(plan["regie"]))
cash=0; cash2=0; subs=0.0; trows=[]; cum_ca=0; prev_cot=0
for i,m in enumerate(mois):
  ca_d=plan["diag"][i]*h["diag"][1]; ca_p=plan["pilote"][i]*h["pilote"][1]; ca_i=plan["inst"][i]*h["inst"][1]
  ca_r=plan["regie"][i]*h["regie"][1]
  ca_m=round(subs*h["maint"]); subs+= (plan["pilote"][i]+plan["inst"][i])*h["abo_rate"]
  ca=ca_d+ca_p+ca_i+ca_r+ca_m
  # encaissement : 50 % acompte a la commande, solde M+1 -> simplification : encaissement a 30 jours
  enc = 1500 if i==0 else trows[-1]["CA facture"]  # M0 : apport personnel (hypothese)
  if i==0:
    dec={"VPS KVM 8 + KVM 2 prepaye 24 mois":-860,"Cles physiques x2":-110,"Depot marque INPI":-270,"e-Soleau":-15,"Domaine + messagerie":-30}
  else:
    dec={"Cotisations + CFP + VL (M-1)":-prev_cot,"Sauvegardes + coffre externe":-10,"IA payante plafonnee":-30,"Outils":-50,
         "RC pro (mensualisee)":-46,"Marketing":-100,"Commission Malt":-round(ca_r*MALT_SHARE*MALT_COM),"Formation":-25,
         "Juridique (relecture CGV/DPA)":-800 if i==2 else 0, "e-Soleau V2.2":-15 if i==3 else 0}
  out=sum(dec.values())
  prev_cot=round(enc*(COT+CFP+VL))  # declaration mensuelle sur encaissements
  cash+=enc+out
  cash2 = (cash2 if i else 0) + enc + out - (1000 if i>=3 else 0)
  trows.append({"mois":m,"CA facture":ca,"dont regie":ca_r,"dont maintenance":ca_m,"encaissements (M0 = apport 1500)":enc,"decaissements":out,"tresorerie fin de mois (avant prelevement personnel)":round(cash),"tresorerie si prelevement 1000 EUR/mois des M3":round(cash2)})
with open(f"{OUT}/tresorerie_an1_central.csv","w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=list(trows[0].keys()),delimiter=";"); w.writeheader(); w.writerows(trows)
# hypotheses csv
hyp=[]
for sc,yrs in S.items():
  for y,h in yrs.items():
    hyp.append([sc,f"An {y}",h["diag"][0],h["diag"][1],h["pilote"][0],h["pilote"][1],h["inst"][0],h["inst"][1],h["maint"],h["abo_rate"],h["regie"][0],h["regie"][1],h["lic"][0],h["lic"][1],h["lic"][2]])
with open(f"{OUT}/hypotheses_previsionnel.csv","w",newline="",encoding="utf-8") as f:
  w=csv.writer(f,delimiter=";"); w.writerow(["scenario","annee","nb_diagnostics","prix_diagnostic_HT","nb_pilotes","prix_pilote_HT","nb_installations","prix_installation_HT","maintenance_HT_mois","taux_souscription_maintenance","jours_regie","TJM_HT","nb_integrateurs","licence_annuelle_HT","redevance_client_mois_HT"]); w.writerows(hyp)
print(json.dumps({sc:{y:{k:v for k,v in d.items() if k not in("ca","ch")} for y,d in s.items()} for sc,s in summary.items()},indent=0))
for sc in summary:
  for y in (1,2,3): print(sc,y,summary[sc][y]["ca"]); print(summary[sc][y]["ch"])
for r in trows: print(r)
