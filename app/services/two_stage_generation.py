async def generate_two_stage(self, user_prompt: str) -> "GenerationResult":
        """
        Phase 4: Two-stage LLM generation (Intent → Template).
        
        Eliminates topology hallucinations by separating reasoning from generation:
        1. LLM extracts design intent (no topology)
        2. Template fills FeatureGraph (validated blueprint)
        
        Args:
            user_prompt: User's natural language description
            
        Returns:
            GenerationResult with template-generated FeatureGraph
        """
        logger.info(f"=== TWO-STAGE GENERATION START ===")
        logger.info(f"User prompt: {user_prompt}")
        
        try:
            # Stage 1: Extract intent
            logger.info("Stage 1: Extracting design intent...")
            intent = await self.llm_client.generate_design_intent(user_prompt)
            logger.info(f"Intent extracted: part_type={intent.part_type}, template={intent.template_name()}")
            
            # Check for missing dimensions
            missing = intent.validate_for_template()
            if missing:
                logger.warning(f"Intent missing dimensions: {missing}")
                # Could add LLM call here to fill missing dims, but for now we error
                from app.domain.feature_graph_v1 import FeatureGraphV1 as FeatureGraph
                return {
                    "success": False,
                    "feature_graph": None,
                    "geometry_files": None,
                    "execution_trace": None,
                    "error_message": f"Missing required dimensions for {intent.part_type}: {missing}",
                    "metadata": {"intent": intent.model_dump()}
                }
            
            # Stage 2: Generate from template
            logger.info("Stage 2: Generating from template...")
            feature_graph = await self.llm_client.generate_from_template(intent)
            logger.info(f"FeatureGraph generated from template: {feature_graph.version}")
            
            # Compile (if using V3 compiler, it will validate geometry)
            logger.info("Compiling template-generated FeatureGraph...")
            step_path, stl_path, glb_path, trace = self.compiler.compile(feature_graph, f"two_stage_{hash(user_prompt)}")
            
            return {
                "success": True,
                "feature_graph": feature_graph.model_dump(),
                "geometry_files": {
                    "step": str(step_path),
                    "stl": str(stl_path),
                    "glb": str(glb_path)
                },
                "execution_trace": trace.model_dump() if trace else None,
                "metadata": {
                    "generation_mode": "two_stage",
                    "template": intent.template_name(),
                    "intent": intent.model_dump()
                }
            }
            
        except Exception as e:
            logger.error(f"Two-stage generation failed: {e}", exc_info=True)
            return {
                "success": False,
                "feature_graph": None,
                "geometry_files": None,
                "execution_trace": None,
                "error_message": f"Two-stage generation failed: {str(e)}",
                "metadata": {"generation_mode": "two_stage"}
            }
