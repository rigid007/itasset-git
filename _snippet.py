def view_work_order(id):







    """查看工单详情"""







    work_order = WorkOrder.query.get_or_404(id)







    users = User.query.order_by(User.username).all()















    # 知识库联动推荐（按设备类型/厂商/工单分类匹配）







    recommended_kb = []







    device = work_order.device







    if device:







        from models.maintenance_models import KnowledgeArticle







        conditions = []







        if device.type:







            conditions.append(KnowledgeArticle.device_type == device.type)







        if device.vendor:







            conditions.append(KnowledgeArticle.vendor == device.vendor)







        if work_order.category:







            conditions.append(KnowledgeArticle.category == work_order.category)







        if conditions:

            recommended_kb = KnowledgeArticle.query.filter_by(status='published') \

                .filter(db.or_(*conditions)) \

                .order_by(KnowledgeArticle.view_count.desc()).limit(5).all()



    return render_template('maintenance/work_order_detail.html', work_order=work_order,







                           users=users, recommended_kb=recommended_kb)