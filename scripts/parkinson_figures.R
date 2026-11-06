# Plot existing deterministic results only; no refitting or data-dependent exclusions.
args <- commandArgs(trailingOnly=TRUE)
if (length(args)!=2) stop("Usage: Rscript parkinson_figures.R MODELS ANALYSIS")
models <- args[1]
analysis <- args[2]
figures <- file.path(analysis,"figures")
dir.create(figures,showWarnings=FALSE)
read <- function(name) read.csv(file.path(analysis,name),check.names=FALSE)
draw <- function(name,fun,width=12,height=8) {
  png(file.path(figures,paste0(name,".png")),width=width*150,height=height*150,res=150)
  fun(); dev.off()
  pdf(file.path(figures,paste0(name,".pdf")),width=width,height=height)
  fun(); dev.off()
}
palette <- c(Control="#3978a8",PD="#c45b50")
qc <- read("sample_qc.csv")
pca <- read.csv(file.path(models,"full/pca.csv"))
qc <- merge(qc,pca,by="sample_id",sort=FALSE)
suppressPackageStartupMessages(library(DESeq2))
dds <- readRDS(file.path(models,"full/dds.rds"))
raw_cooks <- SummarizedExperiment::assay(dds,"cooks")
write.csv(data.frame(feature_id=rownames(raw_cooks),
                     raw_max_cooks=apply(raw_cooks,1,max,na.rm=TRUE)),
          file.path(analysis,"full_raw_cooks.csv"),row.names=FALSE)
rm(dds,raw_cooks)
variance <- jsonlite::fromJSON(file.path(models,"full/pca_variance.json"))$variance_fraction
draw("01_quality",function() {
  par(mfrow=c(2,3),mar=c(4,4,3,1))
  for (v in c("age","rin","pmi","library_size","detected_genes","leverage")) {
    value <- qc[[v]]
    boxplot(value~qc$condition,col=palette,main=v,ylab=v,xlab="")
    stripchart(value~qc$condition,vertical=TRUE,method="jitter",add=TRUE,pch=16,
               cex=.65,col=adjustcolor("black",alpha.f=.45))
  }
})
draw("02_pca",function() {
  par(mfrow=c(2,2),mar=c(4.5,4.5,3,1))
  colors <- colorRampPalette(c("#253c72","#e2dfbe","#bc3e38"))(100)
  for (v in c("condition","rin","age","pmi")) {
    if (v=="condition") col <- palette[qc$condition] else {
      breaks <- cut(qc[[v]],breaks=100,include.lowest=TRUE,labels=FALSE)
      col <- colors[breaks]
    }
    plot(qc$PC1,qc$PC2,pch=19,col=col,cex=1.1,
         xlab=sprintf("PC1 (%.1f%%)",100*variance[1]),
         ylab=sprintf("PC2 (%.1f%%)",100*variance[2]),main=paste("VST PCA:",v))
    if (v=="condition") legend("topright",legend=names(palette),col=palette,pch=19,bty="n") else {
      legend("topright",legend=signif(range(qc[[v]]),3),col=colors[c(1,100)],pch=19,bty="n")
    }
  }
  mtext("VST values are not covariate-residualized",side=1,outer=TRUE,line=-1,cex=.9)
})
summary <- read("model_summary.csv")
comparisons <- read("model_comparisons.csv")
draw("03_model_sensitivity",function() {
  par(mfrow=c(1,2),mar=c(8,5,3,1))
  bars <- rbind(summary$significant_up,summary$significant_down)
  colnames(bars) <- summary$model
  barplot(bars,col=c("#bc5348","#3d75a4"),las=2,cex.names=.75,ylab="Genes, FDR <= 0.05",
          ylim=c(0,max(colSums(bars))*1.18),
          main="All fixed model variants")
  legend("topright",legend=c("Higher in PD","Lower in PD"),fill=c("#bc5348","#3d75a4"),bty="n")
  selected <- comparisons[comparisons$reference=="full" & comparisons$alternative %in%
                            c("rin5","rin6","age_overlap","pmi_influence"),]
  main_total <- sum(bars[,summary$model=="full"])
  barplot(selected$shared_significant_same_direction,names.arg=selected$alternative,las=2,
          ylim=c(0,main_total*1.12),
          col="#4b918c",ylab="Significant in main and variant, same sign",main="Sensitivity intersections")
  abline(h=summary$significant_up[summary$model=="full"]+summary$significant_down[summary$model=="full"],lty=2)
})
genes <- read("full_annotated.csv")
unadjusted <- read.csv(file.path(models,"unadjusted/all_results.csv"))
paired <- merge(genes,unadjusted,by="feature_id",suffixes=c("_full","_unadjusted"))
draw("04_effects",function() {
  par(mfrow=c(1,2),mar=c(4.5,4.5,3,1))
  finite <- is.finite(paired$padj_full) & is.finite(paired$padj_unadjusted)
  smoothScatter(paired$log2FoldChange_unadjusted[finite],paired$log2FoldChange_full[finite],
                xlab="Unadjusted log2 fold change",ylab="Full model log2 fold change",
                main="Effects: shared finite adjusted p-values")
  abline(0,1,col="#c45b50",lty=2)
  visible <- is.finite(genes$padj) & is.finite(genes$log2FoldChange)
  q <- genes$padj[visible]
  effects <- genes$log2FoldChange[visible]
  col <- ifelse(q<=.05,ifelse(effects>0,"#bc5348","#3d75a4"),"#b7b7b7")
  plot(effects,-log10(pmax(q,1e-300)),pch=16,cex=.35,col=col,
       xlab="Full model log2(PD / Control)",ylab="-log10(FDR)",main="Adjusted differential expression")
  abline(h=-log10(.05),lty=2)
})
panel <- read("pd_gene_panel.csv")
draw("05_pd_genes",function() {
  par(mar=c(5,7,4,2))
  y <- seq_len(nrow(panel))
  limits <- range(panel$ci95_low,panel$ci95_high,na.rm=TRUE)
  plot(panel$log2FoldChange,y,xlim=limits,yaxt="n",pch=19,
       col=ifelse(!is.na(panel$padj)&panel$padj<=.05,"#c45b50","#3978a8"),
       ylab="",xlab="Full model log2(PD / Control), unshrunk 95% Wald interval",
       main="Predefined Parkinson and dopamine gene panel")
  segments(panel$ci95_low,y,panel$ci95_high,y,col="#666666")
  axis(2,at=y,labels=panel$symbol,las=2)
  abline(v=0,lty=2)
  mtext(sprintf("%d/%d genes pass FDR <= 0.05; intervals are not multiplicity adjusted",
                sum(panel$padj<=.05,na.rm=TRUE),nrow(panel)),side=3,line=.4,cex=.85)
},width=10,height=7)
draw("06_top_gene_heatmap",function() {
  par(oma=c(2,0,4,0))
  vst <- as.matrix(read.csv(file.path(models,"full/vst_matrix.csv"),row.names=1,check.names=FALSE))
  selected <- head(genes$feature_id[order(genes$padj,na.last=NA)],30)
  z <- t(scale(t(vst[as.character(selected),,drop=FALSE])))
  z[z>2.5] <- 2.5; z[z< -2.5] <- -2.5
  ordered <- order(qc$condition,qc$rin,qc$sample_id)
  annotation <- genes$symbol[match(rownames(z),genes$feature_id)]
  annotation[is.na(annotation)|annotation==""] <- rownames(z)[is.na(annotation)|annotation==""]
  heatmap(z[,qc$sample_id[ordered],drop=FALSE],Rowv=NA,Colv=NA,scale="none",
          col=colorRampPalette(c("#2c5f91","white","#b74b43"))(101),
          ColSideColors=palette[qc$condition[ordered]],labCol=NA,labRow=annotation,
          margins=c(3,8),cexRow=.75,main="")
  mtext("Top 30 by full-model FDR: row-z VST (same-data selection)",side=3,outer=TRUE,line=1,cex=1.1)
  mtext("Top bar: Control (blue), PD (red); cells: row-z VST -2.5 (blue) to +2.5 (red)",
        side=1,outer=TRUE,line=.3,cex=.85)
},width=12,height=10)
if (file.exists(file.path(analysis,"ora_full_up.csv"))) {
  draw("07_reactome",function() {
    par(mfrow=c(1,2),mar=c(5,17,4,2))
    for (direction in c("up","down")) {
      x <- read(paste0("ora_full_",direction,".csv"))
      x <- head(x[order(x$padj,x$pvalue),],12)
      if (!nrow(x)) { plot.new(); title(paste(direction,"no eligible pathways")); next }
      x <- x[nrow(x):1,]
      x$name <- vapply(x$pathway_name,function(label)
        paste(strwrap(label,width=40),collapse="\n"),character(1))
      plot(x$fold_enrichment,seq_len(nrow(x)),pch=19,cex=1+sqrt(x$overlap)/5,
           col=ifelse(x$padj<=.05,"#a64b49","#909090"),yaxt="n",xlab="Fold enrichment",
           ylab="",main=paste("Higher" ,ifelse(direction=="up","in PD","in Control")))
      axis(2,at=seq_len(nrow(x)),labels=x$name,las=2,cex.axis=.65)
      abline(v=1,lty=2)
    }
    mtext("Reactome ORA; each direction is a separate BH family; dot size: overlap",side=1,outer=TRUE,line=-1,cex=.85)
  },width=18,height=10)
}
cat("FIGURES_DONE",length(list.files(figures,pattern="[.]png$")),"PNG/PDF pairs\n")
