# Fixed, user-authorized research models. This is not a production tool/formula API.
prepare_research_metadata <- function(x) {
  required <- c("gsm","donor","group","age at death","rna integrity number (rin)",
                "post mortem index (pmi)","gender (m: male, f: female)")
  if (!all(required %in% names(x))) stop("MISSING_METADATA_COLUMNS")
  if (anyDuplicated(x$gsm)) stop("DUPLICATE_SAMPLE")
  if (anyDuplicated(x$donor)) stop("DUPLICATE_DONOR")
  if (anyNA(x[,required]) || any(!nzchar(as.matrix(x[,required])))) stop("MISSING_COVARIATE")
  if (!all(x$group %in% c("Control","PD"))) stop("INVALID_CONDITION")
  if (!all(x[["gender (m: male, f: female)"]] %in% c("M","F"))) stop("INVALID_SEX")
  result <- data.frame(sample_id=x$gsm,donor=x$donor,
                       condition=factor(x$group,levels=c("Control","PD")),
                       sex=factor(x[["gender (m: male, f: female)"]],levels=c("F","M")),
                       stringsAsFactors=FALSE)
  result$age <- suppressWarnings(as.numeric(x[["age at death"]]))
  result$rin <- suppressWarnings(as.numeric(x[["rna integrity number (rin)"]]))
  result$pmi <- suppressWarnings(as.numeric(x[["post mortem index (pmi)"]]))
  if (any(!is.finite(as.matrix(result[,c("age","rin","pmi")])))) stop("MISSING_COVARIATE")
  if (any(result$age<=0 | result$rin<=0 | result$rin>10 | result$pmi<0)) stop("INVALID_COVARIATE")
  for (name in c("age","rin","pmi")) {
    if (sd(result[[name]])==0) stop("CONSTANT_COVARIATE")
    result[[paste0(name,"_z")]] <- as.numeric(scale(result[[name]]))
  }
  rownames(result) <- result$sample_id
  result
}

research_subset <- function(metadata, selection) {
  switch(selection,
         full=rep(TRUE,nrow(metadata)),
         rin5=metadata$rin>=5,
         rin6=metadata$rin>=6,
         age_overlap=metadata$age>=65 & metadata$age<=90,
         pmi_influence=metadata$sample_id!="GSM6212963",
         stop("UNKNOWN_RESEARCH_SUBSET"))
}

check_research_design <- function(metadata, design) {
  if (any(table(metadata$condition)<3)) stop("INSUFFICIENT_GROUP_SIZE")
  matrix <- model.matrix(design,metadata)
  decomposition <- qr(matrix)
  if (decomposition$rank!=ncol(matrix)) stop("RANK_DEFICIENT")
  if (nrow(matrix)-ncol(matrix)<3) stop("INSUFFICIENT_RESIDUAL_DF")
  list(rank=decomposition$rank,parameters=ncol(matrix),
       condition_number=kappa(matrix,exact=TRUE),
       leverage=rowSums(qr.Q(decomposition)^2))
}

research_models <- function() {
  full <- ~age_z+sex+rin_z+pmi_z+condition
  list(
    unadjusted=list(design=~condition,subset="full",uniform_cooks=FALSE),
    demographics=list(design=~age_z+sex+condition,subset="full",uniform_cooks=FALSE),
    demographics_rin=list(design=~age_z+sex+rin_z+condition,subset="full",uniform_cooks=FALSE),
    full=list(design=full,subset="full",uniform_cooks=FALSE),
    rin5=list(design=full,subset="rin5",uniform_cooks=FALSE),
    rin6=list(design=full,subset="rin6",uniform_cooks=FALSE),
    age_overlap=list(design=full,subset="age_overlap",uniform_cooks=FALSE),
    pmi_influence=list(design=full,subset="pmi_influence",uniform_cooks=FALSE),
    unadjusted_uniform=list(design=~condition,subset="full",uniform_cooks=TRUE),
    full_uniform=list(design=full,subset="full",uniform_cooks=TRUE)
  )
}

fit_research_model <- function(counts, metadata, specification, output) {
  selected <- research_subset(metadata,specification$subset)
  current <- droplevels(metadata[selected,,drop=FALSE])
  diagnostics <- check_research_design(current,specification$design)
  subset_counts <- counts[,current$sample_id,drop=FALSE]
  nonzero <- rowSums(subset_counts)>0
  subset_counts <- subset_counts[nonzero,,drop=FALSE]
  storage.mode(subset_counts) <- "integer"
  dds <- DESeq2::DESeqDataSetFromMatrix(subset_counts,current,design=specification$design)
  if (specification$uniform_cooks) {
    dds <- DESeq2::DESeq(dds,quiet=TRUE,parallel=FALSE,minReplicatesForReplace=Inf)
    results <- DESeq2::results(dds,contrast=c("condition","PD","Control"),
                              alpha=.05,cooksCutoff=FALSE)
  } else {
    dds <- DESeq2::DESeq(dds,quiet=TRUE,parallel=FALSE)
    results <- DESeq2::results(dds,contrast=c("condition","PD","Control"),alpha=.05)
  }
  table <- as.data.frame(results)
  table$feature_id <- rownames(table)
  table$ci95_low <- table$log2FoldChange-1.96*table$lfcSE
  table$ci95_high <- table$log2FoldChange+1.96*table$lfcSE
  table <- table[,c("feature_id",setdiff(names(table),"feature_id"))]
  write.csv(table,file.path(output,"all_results.csv"),row.names=FALSE,na="")
  write.csv(current,file.path(output,"samples.csv"),row.names=FALSE)
  replacement <- S4Vectors::mcols(dds)$replace
  if (is.null(replacement)) replacement <- rep(FALSE,nrow(dds))
  max_cooks <- S4Vectors::mcols(dds)$maxCooks
  if (is.null(max_cooks)) max_cooks <- rep(NA_real_,nrow(dds))
  write.csv(data.frame(feature_id=rownames(dds),replaced=replacement,max_cooks=max_cooks),
            file.path(output,"gene_diagnostics.csv"),row.names=FALSE,na="")
  threshold <- qf(.99,diagnostics$parameters,nrow(current)-diagnostics$parameters)
  sample_diagnostics <- data.frame(sample_id=current$sample_id,
                                   library_size=colSums(subset_counts),
                                   detected_genes=colSums(subset_counts>0),
                                   size_factor=DESeq2::sizeFactors(dds),
                                   leverage=diagnostics$leverage)
  if ("cooks" %in% SummarizedExperiment::assayNames(dds)) {
    cooks <- SummarizedExperiment::assay(dds,"cooks")
    sample_diagnostics$cook_genes_over_f99 <- colSums(cooks>threshold,na.rm=TRUE)
    sample_diagnostics$cook_p99 <- apply(cooks,2,quantile,.99,na.rm=TRUE)
  }
  write.csv(sample_diagnostics,file.path(output,"sample_diagnostics.csv"),row.names=FALSE)
  filter_metadata <- S4Vectors::metadata(results)
  filter_threshold <- as.numeric(filter_metadata$filterThreshold)
  significant <- !is.na(table$padj) & table$padj<=.05
  summary <- list(
    design=paste(deparse(specification$design),collapse=""),
    contrast=c("condition","PD","Control"),subset=specification$subset,
    uniform_cooks=specification$uniform_cooks,n_samples=nrow(current),
    group_counts=as.list(table(current$condition)),input_genes=nrow(counts),
    all_zero_removed=sum(!nonzero),result_genes=nrow(table),
    pvalue_available=sum(is.finite(table$pvalue)),padj_available=sum(is.finite(table$padj)),
    padj_na=sum(is.na(table$padj)),pvalue_na=sum(is.na(table$pvalue)),
    significant_up=sum(significant & table$log2FoldChange>0,na.rm=TRUE),
    significant_down=sum(significant & table$log2FoldChange<0,na.rm=TRUE),
    replaced_genes=sum(replacement,na.rm=TRUE),replace_assay_present="replaceCounts" %in% SummarizedExperiment::assayNames(dds),
    filter_threshold=filter_threshold,filter_theta=as.numeric(filter_metadata$filterTheta),
    model_rank=diagnostics$rank,model_parameters=diagnostics$parameters,
    condition_number=diagnostics$condition_number,cook_f99_diagnostic_threshold=threshold,
    results_names=DESeq2::resultsNames(dds),elapsed_finished_at=format(Sys.time(),tz="UTC",usetz=TRUE)
  )
  jsonlite::write_json(summary,file.path(output,"summary.json"),auto_unbox=TRUE,pretty=TRUE,na="null")
  list(dds=dds,summary=summary)
}

parkinson_research_main <- function() {
  arguments <- commandArgs(trailingOnly=TRUE)
  if (length(arguments)!=3) stop("Usage: Rscript parkinson_models.R counts.tsv metadata.csv NEW_OUTPUT")
  if (dir.exists(arguments[3])) stop("OUTPUT_MUST_BE_NEW")
  dir.create(arguments[3],recursive=TRUE)
  suppressPackageStartupMessages(library(DESeq2))
  set.seed(42)
  counts <- as.matrix(read.delim(arguments[1],row.names=1,check.names=FALSE))
  metadata <- prepare_research_metadata(read.csv(arguments[2],check.names=FALSE))
  if (anyDuplicated(rownames(counts)) || anyDuplicated(colnames(counts))) stop("DUPLICATE_COUNTS_ID")
  if (!setequal(colnames(counts),metadata$sample_id)) stop("SAMPLE_SET_MISMATCH")
  if (any(!is.finite(counts)) || any(counts<0) || any(counts!=floor(counts))) stop("INVALID_RAW_COUNTS")
  write.csv(metadata,file.path(arguments[3],"prepared_metadata.csv"),row.names=FALSE)
  summaries <- list()
  for (name in names(research_models())) {
    message("FIT_START ",name)
    output <- file.path(arguments[3],name)
    dir.create(output)
    fitted <- fit_research_model(counts,metadata,research_models()[[name]],output)
    summaries[[name]] <- fitted$summary
    if (name=="full") {
      saveRDS(fitted$dds,file.path(output,"dds.rds"))
      transformed <- DESeq2::varianceStabilizingTransformation(fitted$dds,blind=FALSE)
      vst <- SummarizedExperiment::assay(transformed)
      pca <- prcomp(t(vst),scale.=FALSE)
      write.csv(data.frame(sample_id=rownames(pca$x),pca$x[,1:3,drop=FALSE]),
                file.path(output,"pca.csv"),row.names=FALSE)
      jsonlite::write_json(list(variance_fraction=(pca$sdev^2/sum(pca$sdev^2))[1:3]),
                           file.path(output,"pca_variance.json"),auto_unbox=TRUE,pretty=TRUE)
      write.csv(vst,file.path(output,"vst_matrix.csv"))
      write.csv(DESeq2::counts(fitted$dds,normalized=TRUE),file.path(output,"normalized_counts.csv"))
      rm(transformed,vst,pca)
    }
    message("FIT_DONE ",name," up=",fitted$summary$significant_up,
            " down=",fitted$summary$significant_down)
    rm(fitted)
    gc(verbose=FALSE)
  }
  jsonlite::write_json(summaries,file.path(arguments[3],"model_summaries.json"),auto_unbox=TRUE,pretty=TRUE,na="null")
  writeLines(capture.output(sessionInfo()),file.path(arguments[3],"sessionInfo.txt"))
}

if (sys.nframe()==0L) parkinson_research_main()
