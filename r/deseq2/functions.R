.deseq2_stop <- function(code, message) {
  stop(paste0(code, ": ", message), call. = FALSE)
}

.deseq2_require <- function(package) {
  if (!requireNamespace(package, quietly = TRUE)) {
    .deseq2_stop(
      "MISSING_R_PACKAGE",
      paste0("required package is not installed: ", package)
    )
  }
}

validate_sample_set <- function(counts, metadata) {
  if (!is.matrix(counts) || is.null(colnames(counts))) {
    .deseq2_stop("INVALID_COUNTS_MATRIX", "counts must have sample column names")
  }
  if (!is.data.frame(metadata) || !("sample_id" %in% colnames(metadata))) {
    .deseq2_stop("MISSING_SAMPLE_ID", "metadata must contain sample_id")
  }

  count_sample_ids <- colnames(counts)
  metadata_sample_ids <- as.character(metadata$sample_id)

  if (anyNA(count_sample_ids) || any(!nzchar(count_sample_ids))) {
    .deseq2_stop("MISSING_SAMPLE_ID", "count sample IDs must be non-empty")
  }
  if (anyNA(metadata_sample_ids) || any(!nzchar(metadata_sample_ids))) {
    .deseq2_stop("MISSING_SAMPLE_ID", "metadata sample IDs must be non-empty")
  }
  if (anyDuplicated(count_sample_ids)) {
    .deseq2_stop("DUPLICATE_SAMPLE_ID", "count sample IDs must be unique")
  }
  if (anyDuplicated(metadata_sample_ids)) {
    .deseq2_stop("DUPLICATE_SAMPLE_ID", "metadata sample IDs must be unique")
  }
  if (length(count_sample_ids) != length(metadata_sample_ids) ||
      !setequal(count_sample_ids, metadata_sample_ids)) {
    .deseq2_stop(
      "SAMPLE_SET_MISMATCH",
      "sample IDs in counts and metadata must match exactly"
    )
  }

  invisible(TRUE)
}

validate_contrast_levels <- function(metadata, factor, numerator, denominator) {
  if (!is.character(factor) || length(factor) != 1L || !nzchar(factor)) {
    .deseq2_stop("MISSING_FACTOR", "factor must be one metadata column name")
  }
  if (!(factor %in% colnames(metadata))) {
    .deseq2_stop("MISSING_FACTOR", "factor column not found in metadata")
  }
  if (!is.character(numerator) || length(numerator) != 1L ||
      !is.character(denominator) || length(denominator) != 1L ||
      !nzchar(numerator) || !nzchar(denominator)) {
    .deseq2_stop(
      "INVALID_COMPARISON_LEVEL",
      "comparison levels must be non-empty strings"
    )
  }
  if (identical(numerator, denominator)) {
    .deseq2_stop(
      "INVALID_COMPARISON_LEVEL",
      "numerator and denominator must differ"
    )
  }

  factor_values <- metadata[[factor]]
  if (anyNA(factor_values) || any(!nzchar(trimws(as.character(factor_values))))) {
    .deseq2_stop(
      "MISSING_FACTOR_VALUE",
      "selected factor must not contain missing values"
    )
  }
  factor_values <- as.character(factor_values)
  observed_levels <- unique(factor_values)
  if (length(observed_levels) != 2L) {
    .deseq2_stop(
      "INVALID_FACTOR_LEVEL_COUNT",
      "selected factor must contain exactly two observed levels"
    )
  }
  if (!(numerator %in% observed_levels) || !(denominator %in% observed_levels)) {
    .deseq2_stop(
      "INVALID_COMPARISON_LEVEL",
      "numerator and denominator must be observed factor levels"
    )
  }

  group_sizes <- table(factor_values)
  if (any(group_sizes[c(numerator, denominator)] < 2L)) {
    .deseq2_stop(
      "INSUFFICIENT_REPLICATES",
      "each comparison level must have at least two samples"
    )
  }

  invisible(TRUE)
}

validate_deseq2_inputs <- function(
  counts,
  metadata,
  factor,
  numerator,
  denominator
) {
  if (!is.matrix(counts) || !is.numeric(counts)) {
    .deseq2_stop("INVALID_COUNTS_MATRIX", "counts must be a numeric matrix")
  }
  if (is.null(rownames(counts)) || anyNA(rownames(counts)) ||
      any(!nzchar(rownames(counts)))) {
    .deseq2_stop("MISSING_FEATURE_ID", "counts must have non-empty feature IDs")
  }
  if (anyDuplicated(rownames(counts))) {
    .deseq2_stop("DUPLICATE_FEATURE_ID", "feature IDs must be unique")
  }
  if (any(!is.finite(counts))) {
    .deseq2_stop("NON_FINITE_COUNT", "counts must be finite")
  }
  if (any(counts < 0)) {
    .deseq2_stop("NEGATIVE_COUNT", "counts must be non-negative")
  }
  if (any(counts != floor(counts))) {
    .deseq2_stop("NON_INTEGER_COUNT", "counts must be integer-valued")
  }
  if (any(counts > .Machine$integer.max)) {
    .deseq2_stop("COUNT_OUT_OF_RANGE", "counts exceed the R integer range")
  }
  if (any(colSums(counts) <= 0)) {
    .deseq2_stop("ZERO_LIBRARY_SIZE", "all samples must have a positive library")
  }

  validate_sample_set(counts, metadata)
  validate_contrast_levels(metadata, factor, numerator, denominator)
  invisible(TRUE)
}

make_bulk_fixture <- function(seed = 42L) {
  set.seed(seed)

  feature_ids <- sprintf("GENE_%03d", seq_len(200L))
  control_samples <- sprintf("Control_%d", seq_len(3L))
  ad_samples <- sprintf("AD_%d", seq_len(3L))
  sample_ids <- c(control_samples, ad_samples)

  counts <- matrix(
    as.integer(rnbinom(200L * 6L, mu = 100, size = 10)),
    nrow = 200L,
    ncol = 6L,
    dimnames = list(feature_ids, sample_ids)
  )
  counts["GENE_001", control_samples] <- c(40L, 50L, 60L)
  counts["GENE_001", ad_samples] <- c(800L, 900L, 1000L)

  metadata <- data.frame(
    sample_id = sample_ids,
    condition = c(rep("Control", 3L), rep("AD", 3L)),
    row.names = sample_ids,
    stringsAsFactors = FALSE,
    check.names = FALSE
  )

  list(counts = counts, metadata = metadata)
}

.stable_result_table <- function(result) {
  result_table <- as.data.frame(result, stringsAsFactors = FALSE)
  result_table$feature_id <- rownames(result_table)
  result_table <- result_table[
    , c("feature_id", setdiff(names(result_table), "feature_id")),
    drop = FALSE
  ]
  padj_key <- ifelse(is.na(result_table$padj), Inf, result_table$padj)
  pvalue_key <- ifelse(is.na(result_table$pvalue), Inf, result_table$pvalue)
  sort_index <- order(
    padj_key,
    pvalue_key,
    result_table$feature_id,
    method = "radix"
  )
  result_table <- result_table[sort_index, , drop = FALSE]
  rownames(result_table) <- result_table$feature_id
  result_table
}

run_deseq2 <- function(
  counts,
  metadata,
  factor,
  numerator,
  denominator,
  alpha = 0.05,
  lfc_shrink = TRUE
) {
  if (!is.numeric(alpha) || length(alpha) != 1L || !is.finite(alpha) ||
      alpha <= 0 || alpha >= 1) {
    .deseq2_stop("INVALID_ALPHA", "alpha must be a finite number in (0, 1)")
  }
  if (!is.logical(lfc_shrink) || length(lfc_shrink) != 1L || is.na(lfc_shrink)) {
    .deseq2_stop("INVALID_SHRINK_OPTION", "lfc_shrink must be TRUE or FALSE")
  }
  validate_deseq2_inputs(counts, metadata, factor, numerator, denominator)
  .deseq2_require("DESeq2")
  if (isTRUE(lfc_shrink)) {
    .deseq2_require("apeglm")
  }

  ordered_metadata <- metadata[match(colnames(counts), metadata$sample_id), , drop = FALSE]
  rownames(ordered_metadata) <- ordered_metadata$sample_id
  design_factor <- "bioagent_condition"
  ordered_metadata[[design_factor]] <- relevel(
    factor(as.character(ordered_metadata[[factor]])),
    ref = denominator
  )
  integer_counts <- counts
  storage.mode(integer_counts) <- "integer"

  dds <- DESeq2::DESeqDataSetFromMatrix(
    countData = integer_counts,
    colData = ordered_metadata,
    design = ~bioagent_condition
  )
  dds <- DESeq2::DESeq(dds, quiet = TRUE)
  raw_results <- DESeq2::results(
    dds,
    contrast = c(design_factor, numerator, denominator),
    alpha = alpha
  )
  final_results <- raw_results
  if (isTRUE(lfc_shrink)) {
    coefficient_names <- setdiff(DESeq2::resultsNames(dds), "Intercept")
    if (length(coefficient_names) != 1L) {
      .deseq2_stop(
        "INVALID_LFC_COEFFICIENT",
        "exactly one non-intercept coefficient is required for shrinkage"
      )
    }
    shrunk_results <- DESeq2::lfcShrink(
      dds,
      coef = coefficient_names[[1L]],
      res = raw_results,
      type = "apeglm"
    )
    if (!identical(rownames(shrunk_results), rownames(raw_results))) {
      .deseq2_stop("INVALID_SHRINK_FEATURES", "shrinkage changed feature alignment")
    }
    # apeglm omits stat: it is not a statistic of the posterior estimates.
    # Keep the original Wald test and alpha-specific p-values, replacing only
    # the effect estimate and its uncertainty (posterior SD when shrunk).
    final_results$log2FoldChange <- shrunk_results$log2FoldChange
    final_results$lfcSE <- shrunk_results$lfcSE
  }

  result_table <- .stable_result_table(final_results)
  normalized_counts <- DESeq2::counts(dds, normalized = TRUE)
  variance_stabilized <- DESeq2::varianceStabilizingTransformation(dds, blind = FALSE)
  pca_fit <- stats::prcomp(
    t(SummarizedExperiment::assay(variance_stabilized)),
    scale. = FALSE
  )
  pca_data <- as.data.frame(
    pca_fit$x[, seq_len(min(2L, ncol(pca_fit$x))), drop = FALSE]
  )
  pca_data$sample_id <- rownames(pca_data)
  pca_data$factor_level <- as.character(ordered_metadata[[factor]])
  rownames(pca_data) <- NULL

  size_factors <- data.frame(
    sample_id = names(DESeq2::sizeFactors(dds)),
    size_factor = as.numeric(DESeq2::sizeFactors(dds)),
    stringsAsFactors = FALSE
  )
  summary <- list(
    status = "success",
    factor = factor,
    numerator = numerator,
    denominator = denominator,
    alpha = alpha,
    lfc_shrink = isTRUE(lfc_shrink),
    n_features = nrow(counts),
    n_samples = ncol(counts),
    significant_count = sum(!is.na(result_table$padj) & result_table$padj <= alpha),
    metadata_reordered = !identical(as.character(metadata$sample_id), colnames(counts)),
    results_names = DESeq2::resultsNames(dds),
    session_info = capture.output(utils::sessionInfo())
  )

  list(
    dds = dds,
    table = result_table,
    normalized_counts = normalized_counts,
    pca = pca_data,
    size_factors = size_factors,
    summary = summary
  )
}

.write_plot_pair <- function(output_dir, stem, plot_function) {
  png_path <- file.path(output_dir, "figures", paste0(stem, ".png"))
  pdf_path <- file.path(output_dir, "figures", paste0(stem, ".pdf"))
  grDevices::png(png_path, width = 1200, height = 900, res = 150)
  tryCatch(plot_function(), finally = grDevices::dev.off())
  grDevices::pdf(pdf_path, width = 8, height = 6)
  tryCatch(plot_function(), finally = grDevices::dev.off())
  c(
    file.path("figures", paste0(stem, ".png")),
    file.path("figures", paste0(stem, ".pdf"))
  )
}

write_deseq2_outputs <- function(result, output_dir) {
  required_fields <- c(
    "dds", "table", "normalized_counts", "pca", "size_factors", "summary"
  )
  if (!is.list(result) || !identical(names(result), required_fields)) {
    .deseq2_stop("INVALID_RESULT", "result fields do not match the DESeq2 contract")
  }
  .deseq2_require("jsonlite")
  .deseq2_require("pheatmap")
  dir.create(file.path(output_dir, "results"), recursive = TRUE, showWarnings = FALSE)
  dir.create(file.path(output_dir, "figures"), recursive = TRUE, showWarnings = FALSE)

  result_table <- result$table
  alpha <- result$summary$alpha
  significant <- result_table[
    !is.na(result_table$padj) & result_table$padj <= alpha,
    ,
    drop = FALSE
  ]
  normalized_table <- data.frame(
    feature_id = rownames(result$normalized_counts),
    result$normalized_counts,
    check.names = FALSE
  )
  size_factor_table <- result$size_factors

  utils::write.csv(
    result_table,
    file.path(output_dir, "results", "all_results.csv"),
    row.names = FALSE
  )
  utils::write.csv(
    significant,
    file.path(output_dir, "results", "significant_results.csv"),
    row.names = FALSE
  )
  utils::write.csv(
    normalized_table,
    file.path(output_dir, "results", "normalized_counts.csv"),
    row.names = FALSE
  )
  utils::write.csv(result$pca, file.path(output_dir, "results", "pca.csv"), row.names = FALSE)
  utils::write.csv(
    size_factor_table,
    file.path(output_dir, "results", "size_factors.csv"),
    row.names = FALSE
  )
  jsonlite::write_json(
    result$summary,
    file.path(output_dir, "results", "execution_summary.json"),
    auto_unbox = TRUE,
    pretty = TRUE,
    na = "null"
  )
  writeLines(result$summary$session_info, file.path(output_dir, "results", "session_info.txt"))

  pca_plot <- function() {
    pca_columns <- grep("^PC", names(result$pca), value = TRUE)
    second_column <- pca_columns[[min(2L, length(pca_columns))]]
    graphics::plot(
      result$pca[[pca_columns[[1L]]]],
      result$pca[[second_column]],
      col = as.factor(result$pca$factor_level),
      pch = 19,
      xlab = pca_columns[[1L]],
      ylab = second_column,
      main = "PCA"
    )
    graphics::text(
      result$pca[[pca_columns[[1L]]]],
      result$pca[[second_column]],
      labels = result$pca$sample_id,
      pos = 3,
      cex = 0.7
    )
  }
  paths <- .write_plot_pair(output_dir, "pca", pca_plot)

  correlation <- stats::cor(log2(result$normalized_counts + 1))
  pheatmap_paths <- c(
    file.path("figures", "sample_correlation_heatmap.png"),
    file.path("figures", "sample_correlation_heatmap.pdf")
  )
  pheatmap::pheatmap(
    correlation,
    filename = file.path(output_dir, pheatmap_paths[[1L]]),
    silent = TRUE
  )
  pheatmap::pheatmap(
    correlation,
    filename = file.path(output_dir, pheatmap_paths[[2L]]),
    silent = TRUE
  )
  paths <- c(paths, pheatmap_paths)

  ma_plot <- function() {
    graphics::plot(
      result_table$baseMean,
      result_table$log2FoldChange,
      log = "x",
      pch = 19,
      cex = 0.5,
      xlab = "Mean normalized count",
      ylab = "log2 fold change",
      main = "MA plot"
    )
    graphics::abline(h = 0, col = "grey50")
  }
  paths <- c(paths, .write_plot_pair(output_dir, "ma_plot", ma_plot))

  volcano_plot <- function() {
    p_values <- result_table$pvalue
    y_values <- -log10(pmax(p_values, .Machine$double.xmin))
    y_values[is.na(p_values)] <- NA_real_
    graphics::plot(
      result_table$log2FoldChange,
      y_values,
      pch = 19,
      cex = 0.5,
      xlab = "log2 fold change",
      ylab = "-log10 p-value",
      main = "Volcano plot"
    )
  }
  paths <- c(paths, .write_plot_pair(output_dir, "volcano_plot", volcano_plot))

  paths <- c(
    "results/all_results.csv",
    "results/significant_results.csv",
    "results/normalized_counts.csv",
    "results/pca.csv",
    "results/size_factors.csv",
    "results/execution_summary.json",
    "results/session_info.txt",
    paths
  )
  as.character(paths)
}
